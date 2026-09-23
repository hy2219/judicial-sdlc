; This installer changes only its own product files and shortcuts.
; It does not disable security controls or run the installed application.
#ifndef PayloadDir
  #error PayloadDir is required
#endif
#ifndef OutputDir
  #error OutputDir is required
#endif
#ifndef NoticeFile
  #error NoticeFile is required
#endif
#ifndef PayloadManifest
  #error PayloadManifest is required
#endif
#ifndef ProductId
  #error ProductId is required
#endif
#ifndef ProductSlug
  #error ProductSlug is required
#endif
#ifndef PackageVersion
  #error PackageVersion is required
#endif

[Setup]
AppId={#ProductId}
AppName=Judicial Workflow ({#ProductSlug})
AppVersion={#PackageVersion}
AppPublisher=Judicial SDLC Workshop
DefaultDirName={commonpf}\Judicial-SDLC\{#ProductSlug}
DefaultGroupName=Judicial-SDLC\{#ProductSlug}
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableDirPage=yes
DisableProgramGroupPage=yes
UsePreviousAppDir=no
OutputDir={#OutputDir}
OutputBaseFilename=workflow-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
Uninstallable=yes
UninstallDisplayIcon={app}\workflow-app.exe
CloseApplications=no
RestartApplications=no
SetupLogging=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#PayloadDir}\workflow-app.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#PayloadDir}\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#NoticeFile}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#PayloadManifest}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Judicial Workflow"; Filename: "{app}\workflow-app.exe"; WorkingDir: "{app}"
Name: "{group}\Uninstall"; Filename: "{uninstallexe}"
Name: "{commondesktop}\Judicial Workflow ({#ProductSlug})"; Filename: "{app}\workflow-app.exe"; WorkingDir: "{app}"; Tasks: desktopicon
