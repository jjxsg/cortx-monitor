"""
 ****************************************************************************
 Filename:          systemd_watchdog.py
 Description:       Monitors Centos 7 systemd for service events and notifies
                    the ServiceMsgHandler.  Detects drive add/remove event,
                    performs SMART on drives and notifies DiskMsgHandler.

 Creation Date:     04/27/2015
 Author:            Jake Abernathy

 Do NOT modify or remove this copyright and confidentiality notice!
 Copyright (c) 2001 - $Date: 2015/01/14 $ Seagate Technology, LLC.
 The code contained herein is CONFIDENTIAL to Seagate Technology, LLC.
 Portions are also trade secret. Any use, duplication, derivation, distribution
 or disclosure of this code, for any reason, not expressly authorized is
 prohibited. All other rights are expressly reserved by Seagate Technology, LLC.
 ****************************************************************************
"""
import re
import os
import json
import shutil
import Queue
import pyinotify
import time

from datetime import datetime, timedelta

from framework.base.module_thread import ScheduledModuleThread
from framework.base.internal_msgQ import InternalMsgQ
from framework.utils.service_logging import logger

# Modules that receive messages from this module
from message_handlers.service_msg_handler import ServiceMsgHandler
from message_handlers.disk_msg_handler import DiskMsgHandler

from zope.interface import implements
from sensors.IService_watchdog import IServiceWatchdog

import dbus
from dbus import SystemBus, Interface, Array
import gobject
from dbus.mainloop.glib import DBusGMainLoop
from systemd import journal


class SystemdWatchdog(ScheduledModuleThread, InternalMsgQ):

    implements(IServiceWatchdog)

    SENSOR_NAME       = "SystemdWatchdog"
    PRIORITY          = 2

    # Section and keys in configuration file
    SYSTEMDWATCHDOG    = SENSOR_NAME.upper()
    MONITORED_SERVICES = 'monitored_services'
    SMART_TEST_INTERVAL= 'smart_test_interval'


    @staticmethod
    def name():
        """@return: name of the module."""
        return SystemdWatchdog.SENSOR_NAME

    def __init__(self):
        super(SystemdWatchdog, self).__init__(self.SENSOR_NAME,
                                                  self.PRIORITY)
        # Mapping of services and their status'
        self._service_status = {}
        self._inactive_services = []

        # Mapping of SMART jobs and their properties
        self._smart_jobs = {}

    def initialize(self, conf_reader, msgQlist):
        """initialize configuration reader and internal msg queues"""

        # Initialize ScheduledMonitorThread and InternalMsgQ
        super(SystemdWatchdog, self).initialize(conf_reader)

        # Initialize internal message queues for this module
        super(SystemdWatchdog, self).initialize_msgQ(msgQlist)

        # Retrieves the frequency to run SMART tests on all the drives
        self._smart_interval = self._getSMART_interval()

        # Dict of drives by-id symlink from systemd
        self._drive_by_id = {}

        # Next time to run SMART tests
        self._next_smart_tm = datetime.now() + timedelta(seconds=self._smart_interval)

    def read_data(self):
        """Return the dict of service status'"""
        return self._service_status

    def run(self):
        """Run the monitoring periodically on its own thread."""

        #self._set_debug(True)
        #self._set_debug_persist(True)

        # Allow time for the hpi_monitor to come up
        time.sleep(60)

        # Check for debug mode being activated
        self._read_my_msgQ_noWait()

        self._log_debug("Start accepting requests")

        try:
            # Integrate into the main dbus loop to catch events
            DBusGMainLoop(set_as_default=True)

            # Connect to dbus system wide
            self._bus = SystemBus()

            # Get an instance of systemd1
            systemd = self._bus.get_object("org.freedesktop.systemd1", "/org/freedesktop/systemd1")

            # Use the systemd object to get an interface to the Manager
            self._manager = Interface(systemd, dbus_interface='org.freedesktop.systemd1.Manager')

            # Obtain a disk manager interface for monitoring drives
            disk_systemd = self._bus.get_object('org.freedesktop.UDisks2', '/org/freedesktop/UDisks2')
            self._disk_manager = Interface(disk_systemd, dbus_interface='org.freedesktop.DBus.ObjectManager')

            # Assign callbacks to all devices to capture signals
            self._disk_manager.connect_to_signal('InterfacesAdded', self._interface_added)
            self._disk_manager.connect_to_signal('InterfacesRemoved', self._interface_removed)

            # Notify DiskMsgHandler of available drives and schedule SMART tests
            self._init_drives()

            # Read in the list of services to monitor
            monitored_services = self._get_monitored_services()

            # Retrieve a list of all the service units
            units = self._manager.ListUnits()

            #  Start out assuming their all inactive
            self._inactive_services = list(monitored_services)

            logger.info("SystemdWatchdog, Monitored services listed in conf file: %s" % monitored_services)
            logger.info("SystemdWatchdog, Monitoring the following Services:")

            total = 0
            for unit in units:

                if ".service" in unit[0]:
                    unit_name = unit[0]

                    # Apply the filter from config file if present
                    if monitored_services:
                        if unit_name not in monitored_services:
                            continue
                    logger.info("    " + unit_name)

                    # Remove it from our inactive list; it's alive and well
                    self._inactive_services.remove(unit_name)
                    total += 1

                    # Retrieve an object representation of the systemd unit
                    unit = self._bus.get_object('org.freedesktop.systemd1',
                                                self._manager.GetUnit(unit_name))

                    # Use the systemd unit to get an Interface to call methods
                    Iunit = Interface(unit,
                                      dbus_interface='org.freedesktop.systemd1.Manager')

                    # Connect the PropertiesChanged signal to the unit and assign a callback
                    Iunit.connect_to_signal('PropertiesChanged',
                                            lambda a, b, c, p = unit :
                                            self._on_prop_changed(a, b, c, p),
                                            dbus_interface=dbus.PROPERTIES_IFACE)
                    self._service_status[str(unit)] = "active"

            logger.info("SystemdWatchdog, Total services monitored: %d" % total)

            # Retrieve the main loop which will be called in the run method
            self._loop = gobject.MainLoop()

            # Initialize the gobject threads and get its context
            gobject.threads_init()
            context = self._loop.get_context()

            # Send out the current status of each monitored service
            for service in monitored_services:
                try:
                    msgString = json.dumps({"actuator_request_type": {
                                    "service_watchdog_controller": {
                                        "service_name" : service,
                                        "service_request" : "status",
                                        "previous_state" : "N/A"
                                        }
                                    }
                                 })
                    self._write_internal_msgQ(ServiceMsgHandler.name(), msgString)

                except Exception:
                    logger.exception()

            logger.info("SystemdWatchdog initialization completed")

            # Leave enabled for now, it's not too verbose and handy in logs when status' change
            self._set_debug(True)
            self._set_debug_persist(True)

            # Loop forever iterating over the context
            while self._running == True:
                context.iteration(True)
                time.sleep(2)

                if len(self._inactive_services) > 0:
                    self._examine_inactive_services()

                # Perform SMART tests and refresh drive list on a regular interval
                if datetime.now() > self._next_smart_tm:
                    self._init_drives()

            self._log_debug("SystemdWatchdog gracefully breaking out " \
                                "of dbus Loop, not restarting.")

        except Exception as ae:
            # Check for debug mode being activated when it breaks out of blocking loop
            self._read_my_msgQ_noWait()
            if self.is_running() == True:
                self._log_debug("Ungracefully breaking out of dbus loop with error: %s" 
                                % ae)
                # Let the top level sspl_ll_d know that we have a fatal error
                #  and shutdown so that systemd can restart it
                raise Exception(ae)

        # Reset debug mode if persistence is not enabled
        self._disable_debug_if_persist_false()

        self._log_debug("Finished processing successfully")

    def _update_by_id_paths(self):
        """Updates the global dict of by-id symlinks for each drive"""

        # Refresh the set of managed systemd objects
        self._disk_objects = self._disk_manager.GetManagedObjects()

        # Get a list of all the block devices available in systemd
        re_blocks = re.compile('(?P<path>.*?/block_devices/(?P<id>.*))')
        block_devs = [m.groupdict() for m in
                      [re_blocks.match(path) for path in self._disk_objects.keys()]
                      if m]

        # Retrieve the by-id symlink for each drive and save in a dict with the drive path as key
        for block_dev in block_devs:
            try:
                if self._disk_objects[block_dev['path']].get('org.freedesktop.UDisks2.Block') is not None:
                    # Obtain the list of symlinks for the block device
                    udisk_block = self._disk_objects[block_dev['path']]["org.freedesktop.UDisks2.Block"]
                    symlinks = self._sanitize_dbus_value(udisk_block["Symlinks"])
    
                    # Parse out the wwn symlink if it exists otherwise use the by-id
                    for symlink in symlinks:
                        if "wwwn" in symlink:
                            self._drive_by_id[udisk_block["Drive"]] = symlink
                        elif "by-id" in symlink:
                            self._drive_by_id[udisk_block["Drive"]] = symlink
            except Exception as ae:
                self._log_debug("block_dev unusable: %r" % ae)

    def _schedule_SMART_test(self, drive_path, test_type="short"):
        """Schedules a SMART test to be executed on a drive
           add_interface/remove_interface is the callback
           on completion
        """
        if self._disk_objects[drive_path].get('org.freedesktop.UDisks2.Drive.Ata') is not None:
            self._log_debug("Running SMART on serial: %s" % drive_path)

            udisk_drive_ata = self._disk_objects[drive_path]['org.freedesktop.UDisks2.Drive.Ata']
            dev_obj = self._bus.get_object('org.freedesktop.UDisks2', drive_path)

            # Obtain an interface to the ATA drive and start the SMART test
            idev_obj = Interface(dev_obj, 'org.freedesktop.UDisks2.Drive.Ata')
            idev_obj.SmartSelftestStart(test_type, {})
        else:
            self._log_debug("Drive does not support SMART: %s" % drive_path)

    def _init_drives(self):
        """Notifies DiskMsgHanlder of available drives and schedules a short SMART test"""

        # Update the drive's by-id symlink paths
        self._update_by_id_paths()

        # Good for debugging and seeing values available in all the interfaces so keeping here
        #for object_path, interfaces_and_properties in self._disk_objects.items():
        #    self._print_interfaces_and_properties(interfaces_and_properties)

        # Get a list of all the drive devices available in systemd
        re_drive = re.compile('(?P<path>.*?/drives/(?P<id>.*))')
        drives = [m.groupdict() for m in
                  [re_drive.match(path) for path in self._disk_objects.keys()]
                  if m]

        # Loop through all the drives and initiate a SMART test
        for drive in drives:
            try:
                if self._disk_objects[drive['path']].get('org.freedesktop.UDisks2.Drive') is not None:
                    # Get the drive's serial number
                    udisk_drive = self._disk_objects[drive['path']]['org.freedesktop.UDisks2.Drive']
                    serial_number = str(udisk_drive["Serial"])

                    # If serial number is not present then use the ending of by-id symlink
                    if len(serial_number) == 0:
                        tmp_serial = str(self._drive_by_id[drive['path']].split("/")[-1])

                        # Serial numbers are limited to 20 chars string with drive keyword
                        serial_number = tmp_serial[tmp_serial.rfind("drive"):]

                    # Generate and send an internal msg to DiskMsgHandler that the drive is available
                    self._notify_disk_msg_handler(drive['path'], "OK_None", serial_number)

                    # Schedule a SMART test to begin
                    self._schedule_SMART_test(drive['path'])

            except Exception as ae:
                self._log_debug("_init_drives, Exception: %s" % ae)

        # Update the next time to run SMART tests
        self._next_smart_tm = datetime.now() + timedelta(seconds=self._smart_interval)

    def _examine_inactive_services(self):
        """See if an inactive service has been successfully started
            and if so attach a callback method to its properties
            to detect changes
        """
        for disabled_service in self._inactive_services:
            # Retrieve an object representation of the systemd unit
            unit = self._bus.get_object('org.freedesktop.systemd1',
                                        self._manager.LoadUnit(disabled_service))

            state = unit.Get('org.freedesktop.systemd1.Unit', 'ActiveState',
                             dbus_interface='org.freedesktop.DBus.Properties')

            substate = unit.Get('org.freedesktop.systemd1.Unit', 'SubState',
                             dbus_interface='org.freedesktop.DBus.Properties')

            if state == "active":
                self._log_debug("Service: %s is now active and being monitored!" %
                                disabled_service)
                self._service_status[str(disabled_service)] = str(state) + ":" + str(substate)

                # Use the systemd unit to get an Interface to call methods
                Iunit = Interface(unit,
                                  dbus_interface='org.freedesktop.systemd1.Manager')

                # Connect the PropertiesChanged signal to the unit and assign a callback
                Iunit.connect_to_signal('PropertiesChanged',
                                         lambda a, b, c, p = unit :
                                         self._on_prop_changed(a, b, c, p),
                                         dbus_interface=dbus.PROPERTIES_IFACE)

                self._inactive_services.remove(disabled_service)

                # Send out notification of the state change
                msgString = json.dumps({"actuator_request_type": {
                                    "service_watchdog_controller": {
                                        "service_name" : disabled_service,
                                        "service_request": "status",
                                        "previous_state" : "inactive"
                                        }
                                    }
                                 })
                self._write_internal_msgQ(ServiceMsgHandler.name(), msgString)

        if len(self._inactive_services) == 0:
            self._log_debug("Successfully monitoring all services now!")

    def _get_prop_changed(self, unit, interface, prop_name, changed_properties, invalidated_properties):
        """Retrieves the property that changed"""
        if prop_name in invalidated_properties:
            return unit.Get(interface, prop_name, dbus_interface=dbus.PROPERTIES_IFACE)
        elif prop_name in changed_properties:
            return changed_properties[prop_name]
        else:
            return None

    def _on_prop_changed(self, interface, changed_properties, invalidated_properties, unit):
        """Callback to handle state changes in services"""
        # We're dealing with systemd units so we only care about that interface
        #self._log_debug("_on_prop_changed, interface: %s" % interface)
        if interface != 'org.freedesktop.systemd1.Unit':
            return

        # Get the interface for the unit
        Iunit = Interface(unit, dbus_interface='org.freedesktop.DBus.Properties')

        # Always call methods on the interface not the actual object
        unit_name = Iunit.Get(interface, "Id")

        # self._log_debug("_on_prop_changed, changed_properties: %s" % changed_properties)
        # self._log_debug("_on_prop_changed, invalids: %s" % invalidated_properties)

        state = self._get_prop_changed(unit, interface, "ActiveState",
                                       changed_properties, invalidated_properties)

        substate = self._get_prop_changed(unit, interface, "SubState",
                                          changed_properties, invalidated_properties)

        # The state can change from an incoming json msg to the service msg handler
        #  This provides a catch to make sure that we don't send redundant msgs
        if self._service_status.get(str(unit_name), "") == str(state) + ":" + str(substate):
            return
        else:
            # Update the state in the global dict for later use
            self._log_debug("_on_prop_changed, Service state change detected on unit: %s" % unit_name)
            previous_service_status = self._service_status.get(str(unit_name), "").split(":")[0]
            if not previous_service_status:
                previous_service_status = "inactive"
            self._service_status[str(unit_name)] = str(state) + ":" + str(substate)

        # Only send out a json msg if there was a state or substate change for the service
        if state or substate:
            self._log_debug("_on_prop_changed, State: %s, Substate: %s" % (state, substate))

            # Notify the service message handler to transmit the status of the service
            if unit_name is not None:
                msgString = json.dumps({"actuator_request_type": {
                                "service_watchdog_controller": {
                                    "service_name" : unit_name,
                                    "service_request": "status",
                                    "previous_state" : previous_service_status
                                    }
                                }
                             })
                self._write_internal_msgQ(ServiceMsgHandler.name(), msgString)

                if state == "inactive":
                    self._inactive_services.append(unit_name)

    def _get_monitored_services(self):
        """Retrieves the list of services to be monitored"""
        return self._conf_reader._get_value_list(self.SYSTEMDWATCHDOG,
                                                 self.MONITORED_SERVICES)

    def _interface_added(self, object_path, interfaces_and_properties):
        """Callback for when an interface like drive or SMART job has been added"""
        try:
            self._log_debug("Interface Added")
            self._log_debug("  Object Path: %r" % object_path)

            # Handle drives added
            if interfaces_and_properties.get("org.freedesktop.UDisks2.Drive") is not None:
                # Update the drive's by-id symlink paths
                self._update_by_id_paths()

                serial_number = "{}".format(
                        str(interfaces_and_properties["org.freedesktop.UDisks2.Drive"]["Serial"]))

                # If serial number is not present then use the ending of by-id symlink
                if len(serial_number) == 0:
                    tmp_serial = str(self._drive_by_id[object_path].split("/")[-1])

                    # Serial numbers are limited to 20 chars string with drive keyword
                    serial_number = tmp_serial[tmp_serial.rfind("drive"):]

                self._log_debug("  Serial number: %s" % serial_number)

                # Generate and send an internal msg to DiskMsgHandler
                self._notify_disk_msg_handler(object_path, "OK_None", serial_number)

                # Schedule a conveyance type SMART test on new drives
                self._schedule_SMART_test(object_path, test_type='conveyance')

                # Display info about the added device
                self._print_interfaces_and_properties(interfaces_and_properties)

                # Restart openhpid to update HPI data if it's not available
                internal_json_msg = json.dumps(
                                        {"actuator_request_type": {
                                            "service_controller": {
                                                "service_name" : "openhpid.service",
                                                "service_request": "restart"
                                        }}})
                self._write_internal_msgQ(ServiceMsgHandler.name(), internal_json_msg)

            # Handle jobs like SMART tests being initiated
            elif interfaces_and_properties.get("org.freedesktop.UDisks2.Job") is not None:
               Iprops = interfaces_and_properties.get("org.freedesktop.UDisks2.Job")
               if Iprops.get("Operation") is not None and \
                    Iprops.get("Operation") == "ata-smart-selftest":

                # Save Job properties for use when SMART test finishes
                self._smart_jobs[object_path] = Iprops

                # Display info about the SMART test starting
                self._print_interfaces_and_properties(interfaces_and_properties)

        except Exception as ae:
            self._log_debug("_interface_added: Exception: %r" % ae)

    def _interface_removed(self, object_path, interfaces):
        """Callback for when an interface like drive or SMART job has been removed"""
        self._log_debug("Interface Removed")
        self._log_debug("  Object Path: %r" % object_path)

        for interface in interfaces:
            try:
                # Handle drives removed
                if interface == "org.freedesktop.UDisks2.Drive":
                    # Retrieve the serial number
                    udisk_drive = self._disk_objects[object_path]['org.freedesktop.UDisks2.Drive']
                    serial_number = str(udisk_drive["Serial"])

                    # If serial number is not present then use the ending of by-id symlink
                    if len(serial_number) == 0:
                        tmp_serial = str(self._drive_by_id[object_path].split("/")[-1])

                        # Serial numbers are limited to 20 chars string with drive keyword
                        serial_number = tmp_serial[tmp_serial.rfind("drive"):]

                    self._log_debug("  Serial Number: %s" % serial_number)

                    # Generate and send an internal msg to DiskMsgHandler
                    self._notify_disk_msg_handler(object_path, "EMPTY_None", serial_number)

                # Handle jobs completed like SMART tests 
                elif interface == "org.freedesktop.UDisks2.Job":
                    # Retrieve the saved SMART data when the test was started
                    smart_job = self._smart_jobs.get(object_path)
                    if smart_job is None:
                        self._log_debug("SMART job not found, ignoring: %s" % object_path)
                        return

                    # Loop through all the currently managed objects and retrieve the smart status
                    for disk_path, interfaces_and_properties in self._disk_objects.items():
                        if disk_path in smart_job["Objects"]:
                            # Get the SMART test results and the serial number
                    	    udisk_drive_ata = self._disk_objects[disk_path]['org.freedesktop.UDisks2.Drive.Ata']
                    	    smart_status = str(udisk_drive_ata["SmartSelftestStatus"])

                            udisk_drive = self._disk_objects[disk_path]['org.freedesktop.UDisks2.Drive']
                            serial_number = str(udisk_drive["Serial"])
                            self._log_debug("  Serial Number: %s, SMART status: %s" % (serial_number, smart_status))

                            # Process the SMART status and cleanup
                            self._process_smart_status(disk_path, smart_status, serial_number)
                            self._smart_jobs[object_path] = None
                            return

            except Exception as ae:
            	self._log_debug("interface_removed: Exception: %r" % ae) # Drive was removed during SMART?
                self._log_debug("Possible cause: Job not found because service was recently restarted")

    def _process_smart_status(self, disk_path, smart_status, serial_number):
        """Create the status_reason field and notify disk msg handler"""
        if len(smart_status) == 0:
            self._log_debug("SMART result not ready on drive: %s" % serial_number)
            return

        # Possible SMART status for systemd described at
        # http://udisks.freedesktop.org/docs/latest/gdbus-org.freedesktop.UDisks2.Drive.Ata.html#gdbus-property-org-freedesktop-UDisks2-Drive-Ata.SmartSelftestStatus
        if smart_status.lower() == "success" or \
            smart_status.lower() == "inprogress":
            status_reason = "OK_None"
        elif smart_status.lower() == "interrupted":
            status_reason = "Unknown_smart_interrupted"
        elif smart_status.lower() == "aborted":
            status_reason = "Unknown_smart_aborted"
        elif smart_status.lower() == "fatal":
            status_reason = "Failed_smart_failure"
        elif smart_status.lower() == "error_unknown":
            status_reason = "Failed_smart_unknown"
        elif smart_status.lower() == "error_electrical":
            status_reason = "Failed_smart_electrical_failure"
        elif smart_status.lower() == "error_servo":
            status_reason = "Failed_smart_servo_failure"
        elif smart_status.lower() == "error_read":
            status_reason = "Failed_smart_error_read"
        elif smart_status.lower() == "error_handling":
            status_reason = "Failed_smart_damage"
        else:
            status_reason = "Unknown smart status: {}_unknown".format(smart_status)
            
        # Generate and send an internal msg to DiskMsgHandler
        self._notify_disk_msg_handler(disk_path, status_reason, serial_number)

    def _notify_disk_msg_handler(self, disk_path, status_reason, serial_number):
        """Sends an internal msg to DiskMsgHandler with a drives status"""

        # Retrieve the by-id simlink for the disk
        path_id = self._drive_by_id[disk_path]

        internal_json_msg = {"sensor_response_type" : "disk_status_drivemanager",
                             "status" : status_reason,
                             "serial_number" : serial_number,
                             "path_id" : path_id
                             }
        # Send the event to disk message handler to generate json message
        self._write_internal_msgQ(DiskMsgHandler.name(), internal_json_msg)

    def _sanitize_dbus_value(self, value):
        """Convert certain DBus type combinations so that they are easier to read"""
        if isinstance(value, Array) and value.signature == "ay":
            try:
                return self._decode_ay(value)
            except:
                # Try an array of arrays; 'aay' which is the symlinks
                return list(map(self._decode_ay, value or ()))
        elif isinstance(value, Array) and value.signature == "y":
            return bytearray(value).rstrip(bytearray((0,))).decode('utf-8')
        else:
            return value

    def _decode_ay(self, value):
        """Convert binary blob from DBus queries to strings"""
        if len(value) == 0 or \
           value is None:
            return ''
        elif isinstance(value, unicode):
            return value
        elif isinstance(value, bytes):
            return value.decode('utf-8')
        else:
            # dbus.Array([dbus.Byte]) or any similar sequence type:
            return bytearray(value).rstrip(bytearray((0,))).decode('utf-8')

    def _print_interfaces_and_properties(self, interfaces_and_properties):
        """
        Print a collection of interfaces and properties exported by some object

        The argument is the value of the dictionary _values_, as returned from
        GetManagedObjects() for example. See this for details:
            http://dbus.freedesktop.org/doc/dbus-specification.html#standard-interfaces-objectmanager
        """
        for interface_name, properties in interfaces_and_properties.items():
            self._log_debug("  Interface {}".format(interface_name))
            for prop_name, prop_value in properties.items():
                prop_value = self._sanitize_dbus_value(prop_value)
                self._log_debug("  {}: {}".format(prop_name, prop_value))

    def _getSMART_interval(self):
        """Retrieves the frequency to run SMART tests on all the drives"""
        return int(self._conf_reader._get_value_with_default(self.SYSTEMDWATCHDOG,
                                                         self.SMART_TEST_INTERVAL,
                                                         86400))
    def shutdown(self):
        """Clean up scheduler queue and gracefully shutdown thread"""
        super(SystemdWatchdog, self).shutdown()
