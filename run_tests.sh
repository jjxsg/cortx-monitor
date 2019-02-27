#!/bin/bash -e

####################################################################################
# Performs automated integration tests on SSPL-LL by performing the following
#	1) Pulls the latest packages from the git repo and installs prerequisites
#	2) Uninstalls any previous SSPL-LL installations to avoid interference
#	3) Runs a series of tests by injecting actuator messages into RabbitMQ
#	4) Confirms the proper actuator JSON responses are generated by SSPL-LL
#	5) Manipulates the file system in /var/run/diskmonitor/drive_manager.json
#	6) Confirms the proper sensor JSON responses are generated by SSPL-LL
#	7) Uses Mock objects to inject events simulating external sensors
#
# To apply tests on code perform the following
#	Pull the code to be tested from master or branch
#	1) git clone <-b branch> ssh://[uid]@es-gerrit.xyus.xyratex.com:29418/sspl
#	Change to the sspl directory
#	2) cd sspl
#	Execute this test script
#	3) ./run_tests.sh <role>. Default role will be 'test' and wrong role will be redirected to Usage function
#	It will exit 0 upon success and 1 if any tests failed or had errors
#
#
####################################################################################
# TODO
# 1. Separate the LXC and lettuce, so that lettuce can be invoked separately.
# 2. Create RPM for sspl-test to include lettuce test.

TOP_DIR=$PWD

vm_name=sspl-test
[[ $EUID -ne 0 ]] && sudo=sudo
script_dir=/opt/seagate/sspl/low-level/tests/automated/

Usage()
{
    echo "Usage:
    $0 [role]
where:
    role - {dev|test}. Default is test"
}

execute_test()
{
    $sudo chmod +x $script_dir/run_sspl-ll_tests.sh
    $sudo $script_dir/run_sspl-ll_tests.sh
}

role=${1:-test}

case $role in
"dev")
    # checking if LXC is configured
    which lxc-ls &>/dev/null || { echo "lxc-ls binary wasn't found on system, please configure LXC on the system. Unfortunately it can not be done automatically due to possible range of host OS-es."; exit 1;  }

    [[ $($sudo lxc-ls) =~ "$vm_name" ]]  &&  $sudo lxc-stop -n $vm_name && $sudo lxc-destroy -n $vm_name
    $sudo bash  -c  "lxc-create -n $vm_name -t centos  -- -R 7"
    echo "Xyratex" | $sudo chroot /var/lib/lxc/$vm_name/rootfs passwd --stdin  -u root
    $sudo bash  -c  "lxc-start -d -n $vm_name"

    # we need to wait till yum will be functioning properly, this is the easiest way
    $sudo lxc-attach -n $vm_name  -- bash -c "while :; do yum install -y epel-release && break; done"

    # set hostname
    $sudo lxc-attach -n $vm_name  -- bash -c "echo $vm_name > /etc/hostname"

    # add entry in /etc/hosts
    $sudo lxc-attach -n $vm_name  -- bash -c "echo $(hostname -I) $vm_name >> /etc/hosts"

    # Make /root/sspl directory
    $sudo lxc-attach -n $vm_name -- /usr/bin/mkdir -p "/root/sspl"

    # now we will just copy sources to container
    pushd $TOP_DIR; tar cf -  --owner=0 --group=0 . |  $sudo lxc-attach -n $vm_name -- bash -c 'tar -xf  - -C  /root/sspl'; popd

    # Install required packages
    $sudo lxc-attach -n $vm_name  -- yum -y install httpd python2-pip rpm-build git python-Levenshtein graphviz openssl-devel check-devel python-pep8 doxygen libtool sudo make

    # Install lettuce
    $sudo lxc-attach -n $vm_name  -- pip install lettuce

    # Generate RPMs
    $sudo lxc-attach -n $vm_name  -- /root/sspl/jenkins/build.sh

    # Read VERSION
    BASE_DIR=$(realpath $(dirname $0)/..)
    GIT_VER=$(git rev-parse --short HEAD)
    VERSION=$(cat $BASE_DIR/sspl/VERSION)

    # Extract simulation data
    $sudo lxc-attach -n $vm_name  -- tar xvf /root/sspl/5u84_dcs_dump.tgz -C /tmp

    # Install sspl and libsspl_sec packages
    $sudo lxc-attach -n $vm_name  -- yum -y install /root/sspl/dist/rpmbuild/RPMS/x86_64/libsspl_sec-$VERSION-$GIT_VER.x86_64.rpm
    $sudo lxc-attach -n $vm_name  -- yum -y install /root/sspl/dist/rpmbuild/RPMS/x86_64/libsspl_sec-method_none-$VERSION-$GIT_VER.x86_64.rpm
    $sudo lxc-attach -n $vm_name  -- yum -y install /root/sspl/dist/rpmbuild/RPMS/noarch/sspl-$VERSION-$GIT_VER.noarch.rpm

    # Configure and start RabbitMQ
    $sudo lxc-attach -n $vm_name  --  bash -c 'echo AFYDPNYXGNARCABLNENP >> /var/lib/rabbitmq/.erlang.cookie'
    $sudo lxc-attach -n $vm_name  --  bash -c 'echo AFYDPNYXGNARCABLNENP >> /root/.erlang.cookie'
    $sudo lxc-attach -n $vm_name  --  bash -c 'echo NODENAME=rabbit >> /etc/rabbitmq/rabbitmq-env.conf'
    $sudo lxc-attach -n $vm_name  --  chmod 400 /var/lib/rabbitmq/.erlang.cookie
    $sudo lxc-attach -n $vm_name  --  chmod 400 /root/.erlang.cookie
    $sudo lxc-attach -n $vm_name  --  chown -R rabbitmq:rabbitmq /var/lib/rabbitmq/
    $sudo lxc-attach -n $vm_name  --  chown rabbitmq:rabbitmq /var/lib/rabbitmq/.erlang.cookie
    $sudo lxc-attach -n $vm_name  -- systemctl start rabbitmq-server -l

    # Change setup to vm in sspl configurations
    $sudo lxc-attach -n $vm_name  -- sed -i 's/setup=hw/setup=vm/g' /etc/sspl_ll.conf
    $sudo lxc-attach -n $vm_name  -- /root/sspl/low-level/framework/sspl_init

    # Execute tests
    $sudo lxc-attach -n $vm_name -- bash -c "chmod +x $scrpt_dir/run_sspl-ll_tests.sh"
    $sudo lxc-attach -n $vm_name -- bash -c "$script_dir/run_sspl-ll_tests.sh"
    $sudo lxc-stop -n $vm_name && $sudo lxc-destroy -n $vm_name
    ;;
"test")
    lettuce_version=$(pip list 2> /dev/null | grep -w lettuce | cut -c30- || echo)
    [ ! -z $lettuce_version ] && [ $lettuce_version = "0.2.23" ] || {
        echo "Please install lettuce 0.2.23"
        exit 1
    }
    execute_test
    ;;
*)
    echo "Unknown role supplied"
    Usage
    exit 1
    ;;
esac
retcode=$?
exit $retcode
