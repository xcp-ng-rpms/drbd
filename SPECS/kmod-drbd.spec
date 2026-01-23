Name: kmod-drbd
Summary: Kernel driver for DRBD
Version: 9.2.16
Release: 1.0%{?dist}

# always require a suitable userland
Requires: drbd-utils >= 9.27.0

%global tarball_version %(echo "%{version}" | sed -e "s,%{?dist}$,," -e "s,~,-,")
Source: http://pkg.linbit.com/downloads/drbd/9/drbd-%{tarball_version}.tar.gz

License: GPLv2+
Group: System Environment/Kernel
URL: http://www.drbd.org/
BuildRoot: %(mktemp -ud %{_tmppath}/%{name}-%{version}-XXXXXX)

BuildRequires: coccinelle
BuildRequires: gcc
BuildRequires: perl
%if %{defined kernel_module_package_buildreqs}
BuildRequires: %kernel_module_package_buildreqs
%endif

# XCP-ng patches
#
# Context
# We use a modified version of DRBD due to changes added by linbit
# that impact the mechanism for opening and closing DRBD resources.
# On our side, the cost of changing our use of DRBD is significant
# regarding the code base (risk of breaking a pool, blocking production, etc.),
# however, it would be interesting to review our resource management
# on SMAPIv3 in order to be compatible with the current linbit design.
#
# Patches generated from this repo/branch:
# https://github.com/LINBIT/drbd/tree/restore_exact_open_counts_9.2.16
# with this command: "git format-patch drbd-9.2.16..HEAD^ --no-signature --no-numbered".
#
# The official tarballs to use can be found at this link: https://pkg.linbit.com/
# Never use GitHub tarballs (https://github.com/LINBIT/drbd/tags), which don't work.
# They are created automatically every time a tag is pushed to the repo by linbit.
# Just for understanding purposes: working tarballs can be generated via "make tarball"
# in the root folder of the DRBD project.
Patch1001: 0001-Revert-drbd-rework-autopromote.patch
Patch1002: 0002-Fix-for-Revert-drbd-rework-autopromote.patch
Patch1003: 0003-Fixup-for-recent-commit.patch

# rpmbuild --with gcov to set GCOV_PROFILE=y for make
%bcond_with gcov

# rpmbuild --define "ofed_kernel_dir /usr/src/ofa_kernel/x86_64/4.18.0-147.5.1..."
# to build against an some mlnx-ofa_kernel-devel
%if %{defined ofed_kernel_dir}
%global _ofed_version %(rpm -qf --qf '%%{VERSION}_%%{RELEASE}' '%{ofed_kernel_dir}')
%if "%_ofed_version" == ""
%{error:ofed_kernel_dir should belong to an rpm package}}
%endif
%global _ofed_version_nodash .ofed.%(echo %{?_ofed_version} | sed -r 'y/-/_/; s/\.el[0-9_]+\.%{_arch}$//;')
%global dash_ofed -ofed
%endif

%description
This package contains the kernel modules
for the DRBD core and various transports.

# Concept stolen from sles kernel-module-subpackage:
# include the kernel version in the package version,
# so we can have more than one kmod-drbd.
#
# As stated in the RHEL 9 release documents: There is no kernel Application
# Binary Interface (ABI) guarantee between minor releases of RHEL 9.
# So we need to build distinct kernel module packages for each minor release.
# In fact, we have been doing this since RHEL 6, because there have been
# incompatibilities.
#
# For instance, even though the kABI is still "compatible" in RHEL 6.0 to 6.1,
# the actual functionality differs very much: 6.1 does no longer do BARRIERS,
# but wants FLUSH/FUA instead.
%global _this_latest_kernel_devel %({
	rpm -q --qf '%%{VERSION}-%%{RELEASE}.%%{ARCH}\\n' \\
		$(rpm -qa | egrep "^kernel(-rt|-aarch64)?-devel" | /usr/lib/rpm/redhat/rpmsort -r);
	echo '%%{nil}'; } | head -n 1)
%if 0%{!?kernel_version:1}
%global kernel_version %_this_latest_kernel_devel
%{warn: "XXX selected %kernel_version based on installed kernel-*devel packages"}
%endif

%prep
rm -f %{?my_tmp_files_to_be_removed_in_prep}
%setup -q -n drbd-%{tarball_version}
%patch1001 -p1
%patch1002 -p1
%patch1003 -p1

%build
make -C drbd %{_smp_mflags} all KDIR=/lib/modules/%{kernel_version}/build \
	%{?_ofed_version:BUILD_OFED=1} \
	%{?ofed_kernel_dir:OFED_KERNEL_DIR=%{ofed_kernel_dir}} \
	%{?_ofed_version:OFED_VERSION=%{_ofed_version}} \
	%{?with_gcov:GCOV_PROFILE=y}

%install
export INSTALL_MOD_PATH=%{buildroot}

%if %{defined kernel_module_package_moddir}
export INSTALL_MOD_DIR=%{kernel_module_package_moddir drbd}
%else
export INSTALL_MOD_DIR=extra/drbd
%endif

# Very likely kernel_module_package_moddir did ignore the parameter,
# so we just append it here. The weak-modules magic expects that location.
[ $INSTALL_MOD_DIR = extra ] && INSTALL_MOD_DIR=extra/drbd

make -C drbd install KDIR=/lib/modules/%{kernel_version}/build \
	%{?_ofed_version:BUILD_OFED=1} \
	%{?ofed_kernel_dir:OFED_KERNEL_DIR=%{ofed_kernel_dir}} \
	%{?_ofed_version:OFED_VERSION=%{_ofed_version}} \
	%{?with_gcov:GCOV_PROFILE=y} \
	cmd_depmod=:
    kernelrelease=$(cat /lib/modules/%{kernel_version}/build/include/config/kernel.release || make -s -C /lib/modules/%{kernel_version}/build kernelrelease)
    mv drbd/build-current/.kernel.config.gz drbd/k-config-$kernelrelease.gz

mkdir -p %{buildroot}/etc/depmod.d
find %{buildroot}/lib/modules/*/ -name "*.ko"  -printf "%%P\n" |
sort | sed -ne 's,^extra/\(.*\)/\([^/]*\)\.ko$,\2 \1,p' |
while read -r mod path; do
	printf "override %%-16s * weak-updates/%%s\n" $mod $path
	printf "override %%-16s %%s extra/%%s\n" $mod $kernelrelease $path
done > %{buildroot}/etc/depmod.d/drbd.conf
install -D misc/SECURE-BOOT-KEY-linbit.com.der %{buildroot}/etc/pki/linbit/SECURE-BOOT-KEY-linbit.com.der

%post
if [ -e "/boot/System.map-%{kernel_version}" ]; then
    /usr/sbin/depmod -aeF "/boot/System.map-%{kernel_version}" "%{kernel_version}" > /dev/null || :
fi

modules=( $(find /lib/modules/%{kernel_version}/extra/drbd | grep '\.ko$') )
if [ -x "/sbin/weak-modules" ]; then
    printf '%s\n' "${modules[@]}"     | /sbin/weak-modules --add-modules
fi

%preun
rpm -ql kmod-drbd-%{version} | grep '\.ko$' > /var/run/rpm-kmod-drbd-modules

%postun
if [ -e "/boot/System.map-%{kernel_version}" ]; then
    /usr/sbin/depmod -aeF "/boot/System.map-%{kernel_version}" "%{kernel_version}" > /dev/null || :
fi

modules=( $(cat /var/run/rpm-kmod-drbd-modules) )
rm /var/run/rpm-kmod-drbd-modules
if [ -x "/sbin/weak-modules" ]; then
    printf '%s\n' "${modules[@]}"     | /sbin/weak-modules --remove-modules
fi

# Modify LVM configuration to never scan DRBD devices.
%triggerin -- lvm2
sed -i "s/\# \(global_filter\)[[:space:]]*=.*/\1 = [ \"r|^\/dev\/drbd.*|\" ]/g" %{_sysconfdir}/lvm/lvm.conf
sed -i "s/\# \(global_filter\)[[:space:]]*=.*/\1 = [ \"r|^\/dev\/drbd.*|\" ]/g" %{_sysconfdir}/lvm/master/lvm.conf

%files
%defattr(-,root,root)
%doc COPYING
%doc ChangeLog
%doc drbd/k-config-*.gz
%defattr(644,root,root,755)
/etc/depmod.d/drbd.conf
/etc/pki/linbit/SECURE-BOOT-KEY-linbit.com.der
/lib/modules/%{kernel_version}/extra/drbd/*.ko
/lib/modules/%{kernel_version}/extra/drbd/drbd-kernel-compat/handshake/*.ko

%clean
rm -rf %{buildroot}

%changelog
* Fri Jan 23 2026 Ronan Abhamon <ronan.abhamon@vates.tech> - 9.2.16-1.0
- Remove 0003-drbd-drbd_md_get_buffer-do-not-give-up-early.patch
- Add 0003-Fixup-for-recent-commit.patch

* Mon Dec 08 2025 Ronan Abhamon <ronan.abhamon@vates.tech> - 9.2.15-1.0
- Add 0003-drbd-drbd_md_get_buffer-do-not-give-up-early.patch

* Wed Jun 18 2025 Ronan Abhamon <ronan.abhamon@vates.tech> - 9.2.14-1.0
- Add 0001-Revert-drbd-rework-autopromote.patch
- Add 0002-Fix-for-Revert-drbd-rework-autopromote.patch

* Tue Jan 14 2025 Damien Thenot <damien.thenot@vates.tech> - 9.2.11-1.1
- Rebuild from branch restore_exact_open_counts-v2, repo: https://github.com/LINBIT/drbd, commit: 7ed670f3e64bc1878c07709c1e99bc60d52e5f66

* Wed Nov 20 2024 Damien Thenot <damien.thenot@vates.tech> - 9.2.11-1.0
- Build from branch restore_exact_open_counts-v2

* Tue Nov 05 2024 Ronan Abhamon <ronan.abhamon@vates.tech> - 9.2.10-1.5
- Modify LVM configuration to never scan DRBD devices

* Fri Jul 19 2024 Ronan Abhamon <ronan.abhamon@vates.tech> - 9.2.10-1.4
- Add 0001-Revert-drbd-rework-autopromote.patch

* Mon Jul 15 2024 Ronan Abhamon <ronan.abhamon@vates.tech> - 9.2.10-1.0
- Fix specfile for XCP-ng build env

* Mon Jun  3 2024 Philipp Reisner <phil@linbit.com> - 9.2.10
-  New upstream release.

* Tue Apr 30 2024 Philipp Reisner <phil@linbit.com> - 9.2.9
-  New upstream release.

* Tue Mar 05 2024 Philipp Reisner <phil@linbit.com> - 9.2.8
-  New upstream release.

* Wed Dec 22 2023 Philipp Reisner <phil@linbit.com> - 9.2.7
-  New upstream release.

* Tue Oct 31 2023 Philipp Reisner <phil@linbit.com> - 9.2.6
-  New upstream release.

* Wed Aug 09 2023 Philipp Reisner <phil@linbit.com> - 9.2.5
-  New upstream release.

* Mon Jun 05 2023 Philipp Reisner <phil@linbit.com> - 9.2.4
-  New upstream release.

* Tue Apr 04 2023 Philipp Reisner <phil@linbit.com> - 9.2.3
-  New upstream release.

* Mon Jan 30 2023 Philipp Reisner <phil@linbit.com> - 9.2.2
-  New upstream release.

* Mon Nov 14 2022 Philipp Reisner <phil@linbit.com> - 9.2.1
-  New upstream release.

* Mon Oct 10 2022 Philipp Reisner <phil@linbit.com> - 9.2.0
-  New upstream release.
