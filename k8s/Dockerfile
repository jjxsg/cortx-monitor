FROM centos:7

COPY 3rd_party.repo /etc/yum.repos.d
COPY cortx_iso.repo /etc/yum.repos.d
COPY pip.conf /etc/
COPY requirements.txt /

RUN yum install -y python3
RUN yum install -y hdparam \
                ipmitool \
                lshw python3 \
                python36-dbus \
                python36-gobject \
                python36-paramiko \
                python36-psutil \
                shadow-utils \
                smartmontools \
                systemd-python36 \
                udisks2

RUN  pip3 install  cryptography \
                jsonschema \
                pika pyinotify \
                python-daemon \
                requests \
                zope.component \
                zope.event \
                zope.interface

RUN pip3 install -r /requirements.txt
RUN yum install -y cortx-py-utils
RUN yum install -y cortx-sspl

COPY sspl.conf /etc/sspl.conf
COPY global.conf /etc/sspl_global_config_copy.yaml
COPY machine-id /etc/machine-id

RUN mkdir -p  /var/log/cortx/sspl/sspl.log
RUN touch /var/log/cortx/sspl/

COPY service_logging.py /opt/seagate/cortx/sspl/low-level/framework/utils/service_logging.py
COPY sspl_constants.py /opt/seagate/cortx/sspl/low-level/framework/base/sspl_constants.py
COPY egress_processor.py /opt/seagate/cortx/sspl/low-level/framework/messaging/egress_processor.py
COPY node_hw.py /opt/seagate/cortx/sspl/low-level/sensors/impl/generic/node_hw.py
COPY realstor_enclosure.py /opt/seagate/cortx/sspl/low-level/framework/platforms/realstor/realstor_enclosure.py
COPY message_bus.conf /etc/cortx/message_bus.conf
#ENTRYPOINT ["/opt/seagate/cortx/sspl/low-level/sspl_ll_d"]