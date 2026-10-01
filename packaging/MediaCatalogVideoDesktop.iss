#ifndef BundleDir
  #error BundleDir is required
#endif
#ifndef ReleaseDir
  #error ReleaseDir is required
#endif
#ifndef AppVersion
  #error AppVersion is required (scripts/build-desktop.ps1 reads it from pyproject.toml)
#endif

[Setup]
AppId={code:GetAppId}
AppName=Video Library Organizer
AppVerName=Video Library Organizer {#AppVersion}
AppVersion={#AppVersion}
AppPublisher=Video Library Organizer Project
AppPublisherURL=https://github.com/pony6832/video-library-organizer
DefaultDirName={localappdata}\Programs\MediaCatalogVideoDesktop
DefaultGroupName=Video Library Organizer
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#ReleaseDir}
OutputBaseFilename=VideoLibraryOrganizer-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=app.ico
UninstallDisplayIcon={app}\MediaCatalogVideoDesktop.exe
CreateUninstallRegKey=not IsQAMode
UsePreviousAppDir=not IsQAMode
UsePreviousLanguage=no
CloseApplications=no
RestartApplications=no
SetupLogging=yes
InfoBeforeFile=README-zh-TW.md

[Tasks]
Name: "desktopicon"; Description: "Create desktop shortcut"; Flags: checkedonce; Check: not IsQAMode

[InstallDelete]
; The product was renamed from "Media Catalog Video Desktop"; drop the old
; shortcuts so upgraded machines do not show two icons. Same AppId and exe,
; so the upgrade still happens in place. Never touched in QA installs.
Type: files; Name: "{autodesktop}\Media Catalog Video Desktop.lnk"; Check: not IsQAMode
Type: files; Name: "{autoprograms}\Media Catalog Video Desktop\Media Catalog Video Desktop.lnk"; Check: not IsQAMode
Type: dirifempty; Name: "{autoprograms}\Media Catalog Video Desktop"; Check: not IsQAMode

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Video Library Organizer"; Filename: "{app}\MediaCatalogVideoDesktop.exe"; Check: not IsQAMode
Name: "{autodesktop}\Video Library Organizer"; Filename: "{app}\MediaCatalogVideoDesktop.exe"; Tasks: desktopicon; Check: not IsQAMode

[Run]
Filename: "{app}\MediaCatalogVideoDesktop.exe"; Description: "Launch Video Library Organizer"; Flags: nowait postinstall skipifsilent; Check: not IsQAMode

[Code]
function IsQAMode: Boolean;
begin
  Result := ExpandConstant('{param:QAINSTALL|0}') = '1';
end;

function GetAppId(Param: String): String;
begin
  if IsQAMode then
    Result := 'MediaCatalogVideoDesktop-QA'
  else
    Result := 'MediaCatalogVideoDesktop-02E5D05F-9218-4CC5-B41E-66A759599ADD';
end;

// No UninstallDelete section: never remove source media, results, credentials,
// external tools, model weights or the per-user runtime data directory.
