import os
import struct
import subprocess
import sys
from pathlib import Path

from briefcase.commands import (
    BuildCommand,
    CreateCommand,
    PublishCommand,
    RunCommand,
    UpdateCommand
)
from briefcase.config import BaseConfig
from briefcase.exceptions import BriefcaseCommandError
from briefcase.platforms.windows import WindowsMixin


class WindowsMSIMixin(WindowsMixin):
    output_format = 'msi'

    def bundle_path(self, app):
        return self.platform_path / app.name

    def binary_path(self, app):
        return self.platform_path / app.name / 'SourceDir' / 'python' / 'pythonw.exe'

    def distribution_path(self, app):
        return self.platform_path / '{app.formal_name}-{app.version}.msi'.format(app=app)

    def verify_tools(self):
        # Look for the WiX environment variable
        wix_path = Path(os.getenv('WIX', ''))

        # Set up the paths for the WiX executables we will use.
        self.heat_exe = wix_path / 'bin' / 'heat.exe'
        self.light_exe = wix_path / 'bin' / 'light.exe'
        self.candle_exe = wix_path / 'bin' / 'candle.exe'
        if not (
            wix_path
            and self.heat_exe.exists()
            and self.light_exe.exists()
            and self.candle_exe.exists()
        ):
            raise BriefcaseCommandError("""
WiX Toolset is not installed.

Please install the latest stable release from:

    http://wixtoolset.org/

If WiX is already installed, set the WIX environment variable to the
install path.

If you're using Windows 10, you may need to enable the .NET 3.5 framework
before installing WiX. Open the Control Panel, select "Programs and Features",
then "Turn Windows features on or off". Ensure ".NET Framework 3.5 (Includes
.NET 2.0 and 3.0)" is enabled.
""")


class WindowsMSICreateCommand(WindowsMSIMixin, CreateCommand):
    description = "Create and populate a Windows app packaged as an MSI."

    @property
    def support_package_url(self):
        """
        Gets the URL to the embedded Python support package.

        Python provides redistributable zip files containing the Windows builds,
        making it easy to redistribute Python as part of another software
        package.

        :returns: The support package URL.
        """
        version = "%s.%s.%s" % sys.version_info[:3]
        arch = "amd64" if (struct.calcsize("P") * 8) == 64 else "win32"

        # Python 3.7.2 had to be repackaged for Windows,
        # https://bugs.python.org/issue35596. Use this repackaged link for
        # version 3.7.2, otherwise use the standard link format

        if version == "3.7.2":
            return 'https://www.python.org/ftp/python/%s/python-%s.post1-embed-%s.zip' % (version, version, arch)
        else:
            return 'https://www.python.org/ftp/python/%s/python-%s-embed-%s.zip' % (version, version, arch)

    def install_app_support_package(self, app: BaseConfig):
        """
        Install, then modify the default support package.
        """
        # Install the support package using the normal install logic.
        super().install_app_support_package(app)

        # We need to add a ._pth file to include app and app_packages as
        # part of the standard PYTHONPATH. Write a _pth file directly into
        # the support folder, overwriting the default one.
        version_tag = "{sys.version_info.major}{sys.version_info.minor}".format(
            sys=sys
        )
        pth_file = self.support_path(app) / 'python{version_tag}._pth'.format(
            version_tag=version_tag
        )
        with pth_file.open('w') as f:
            f.write('python{version_tag}.zip\n'.format(version_tag=version_tag))
            f.write(".\n")
            f.write("..\\\\app\n")
            f.write("..\\\\app_packages\n")


class WindowsMSIUpdateCommand(WindowsMSIMixin, UpdateCommand):
    description = "Update an existing Windows app packaged as an MSI."


class WindowsMSIBuildCommand(WindowsMSIMixin, BuildCommand):
    description = "Build an MSI for a Windows app."

    def build_app(self, app: BaseConfig, **kwargs):
        """
        Build an application.

        :param app: The application to build
        """
        print()
        print("[{app.name}] Building MSI...".format(app=app))

        try:
            print()
            print("Compiling application manifest...")
            self.subprocess.run(
                [
                    str(self.heat_exe),
                    "dir",
                    "SourceDir",
                    "-nologo",  # Don't display startup text
                    "-gg",  # Generate GUIDs
                    "-sfrag",  # Suppress fragment generation for directories
                    "-sreg",  # Suppress registry harvesting
                    "-srd",  # Suppress harvesting the root directory
                    "-scom",  # Suppress harvesting COM components
                    "-dr", "BRIEFCASE_CONTENT",  # Root directory reference name
                    "-cg", "BRIEFCASE_COMPONENTS",  # Root component group name
                    "-out", "{app.name}-manifest.wxs".format(app=app),
                ],
                check=True,
                cwd=str(self.bundle_path(app))
            )
        except subprocess.CalledProcessError:
            raise BriefcaseCommandError(
                "Unable to generate manifest for app {app.name}.".format(app=app)
            )

        try:
            print()
            print("Compiling application installer...")
            self.subprocess.run(
                [
                    str(self.candle_exe),
                    "-nologo",  # Don't display startup text
                    "-ext", "WixUtilExtension",
                    "-ext", "WixUIExtension",
                    "{app.name}.wxs".format(app=app),
                    "{app.name}-manifest.wxs".format(app=app),
                ],
                check=True,
                cwd=str(self.bundle_path(app))
            )
        except subprocess.CalledProcessError:
            raise BriefcaseCommandError(
                "Unable to compile app {app.name}.".format(app=app)
            )

        try:
            print()
            print("Linking application installer...")
            self.subprocess.run(
                [
                    str(self.light_exe),
                    "-nologo",  # Don't display startup text
                    "-ext", "WixUtilExtension",
                    "-ext", "WixUIExtension",
                    "-o", str(self.distribution_path(app)),
                    "{app.name}.wixobj".format(app=app),
                    "{app.name}-manifest.wixobj".format(app=app),
                ],
                check=True,
                cwd=str(self.bundle_path(app))
            )
        except subprocess.CalledProcessError:
            print()
            raise BriefcaseCommandError(
                "Unable to link app {app.name}.".format(app=app)
            )


class WindowsMSIRunCommand(WindowsMSIMixin, RunCommand):
    description = "Run a Windows app packaged as an MSI."

    def run_app(self, app: BaseConfig, **kwargs):
        """
        Start the application.

        :param app: The config object for the app
        :param base_path: The path to the project directory.
        """
        print()
        print('[{app.name}] Starting app...'.format(
            app=app
        ))
        try:
            print()
            self.subprocess.run(
                [
                    str(self.binary_path(app)),
                    "-m", app.module_name
                ],
                check=True,
            )
        except subprocess.CalledProcessError:
            print()
            raise BriefcaseCommandError(
                "Unable to start app {app.name}.".format(app=app)
            )


class WindowsMSIPublishCommand(WindowsMSIMixin, PublishCommand):
    description = "Publish a Windows MSI."


# Declare the briefcase command bindings
create = WindowsMSICreateCommand  # noqa
update = WindowsMSIUpdateCommand  # noqa
build = WindowsMSIBuildCommand  # noqa
run = WindowsMSIRunCommand  # noqa
publish = WindowsMSIPublishCommand  # noqa
