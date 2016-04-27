#xyr build defines
# This section will be re-written by Jenkins build system.
%define _xyr_package_name     SSPL-LL
%define _xyr_package_source   sspl-1.0.0.tgz
%define _xyr_package_version  1.0.0
%define _xyr_build_number     10.el7
%define _xyr_pkg_url          http://es-gerrit:8080/sspl
%define _xyr_svn_version      0
#xyr end defines

%define _unpackaged_files_terminate_build 0

Name:       %{_xyr_package_name}
Version:    %{_xyr_package_version}
Release:    %{_xyr_build_number}
Summary:    Installs SSPL-LL
BuildArch:  noarch
Group:      System Environment/Daemons
License:    Seagate Proprietary
URL:        %{_xyr_pkg_url}
Source0:    %{_xyr_package_source}
BuildRoot:  %(mktemp -ud %{_tmppath}/%{name}-%{version}-%{release}-XXXXXX)
BuildRequires: rpm-build
Requires:   python-daemon python-inotify python-jsonschema python-pika rabbitmq-server
Requires:   python-zope-interface python-zope-event python-zope-component python-hpi
Requires:   systemd-python pygobject2 dbus python-psutil libsspl_sec usm_tools udisks2
Requires:   zabbix-agent-lib zabbix-openhpi-config zabbix-collector pyserial python-paramiko
Requires:   pysnmp python-openhpi-baselib hdparm
Requires:   glib2 >= 2.40.0-4 
Requires(pre): shadow-utils

%description
Installs SSPL-LL

%prep
%setup -n sspl/low-level

%build


%install
# Copy config file and service startup to correct locations
mkdir -p %{buildroot}/etc/systemd/system
mkdir -p %{buildroot}/etc/dbus-1/system.d
mkdir -p %{buildroot}/etc/polkit-1/rules.d
mkdir -p %{buildroot}/etc/sspl-ll/templates/snmp

cp files/sspl-ll.service %{buildroot}/etc/systemd/system
cp files/sspl_ll.conf %{buildroot}/etc
cp files/sspl-ll_dbus_policy.conf %{buildroot}/etc/dbus-1/system.d
cp files/sspl-ll_dbus_policy.rules %{buildroot}/etc/polkit-1/rules.d
cp snmp/* %{buildroot}/etc/sspl-ll/templates/snmp

# Copy the service into /opt/seagate/sspl where it will execute from
mkdir -p %{buildroot}/opt/seagate/sspl/low-level
cp -rp . %{buildroot}/opt/seagate/sspl/low-level


%post

# Enable persistent boot information for journald
mkdir -p /var/log/journal
systemctl restart systemd-journald

# Have systemd reload
systemctl daemon-reload

# Enable service to start at boot
systemctl enable sspl-ll

# Create the sspl-ll user and initialize
/opt/seagate/sspl/low-level/framework/sspl_ll_reinit
chown -R sspl-ll:root /opt/seagate/sspl/low-level

# Create a link to low-level cli for easy global access
ln -sf /opt/seagate/sspl/low-level/cli/cli-sspl-ll /usr/bin

# Restart dbus with policy file
systemctl restart dbus


%clean
rm -rf %{buildroot}


%files
%defattr(-,sspl-ll,root,-)
/opt/seagate/sspl/*
%defattr(-,root,root,-)
/etc/systemd/system/sspl-ll.service
/etc/sspl_ll.conf
/etc/dbus-1/system.d/sspl-ll_dbus_policy.conf


%changelog
* Tue Jun 09 2015 Aden Jake Abernathy <aden.j.abernathy@seagate.com>
- Linking into security libraries to apply authentication signatures

* Mon Jun 01 2015 David Adair <dadair@seagate.com>
- Add jenkins-friendly template.  Convert to single tarball for all of sspl.

* Fri May 29 2015 Aden jake Abernathy <aden.j.abernathy@seagate.com> - 1.0.0-9
- Adding request actuator for journald logging, updating systemd unit file
- Adding enabling and disabling of services, moving rabbitmq init script to unit file

* Fri May 01 2015 Aden jake Abernathy <aden.j.abernathy@seagate.com> - 1.0.0-8
- Adding service watchdog module

* Fri Apr 24 2015 Aden jake Abernathy <aden.j.abernathy@seagate.com> - 1.0.0-7
- Updating to run sspl-ll service as sspl-ll user instead of root

* Fri Feb 13 2015 Aden Jake Abernathy <aden.j.abernathy@seagate.com> - 1.0.0-1
- Initial spec file
