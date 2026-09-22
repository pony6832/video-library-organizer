#ifndef BundleDir
  #error BundleDir is required
#endif
#ifndef ReleaseDir
  #error ReleaseDir is required
#endif

[Setup]
AppId={code:GetAppId}
AppName=Media Catalog Video Desktop
AppVersion=0.1.0
AppPublisher=Media Catalog Project
DefaultDirName={localappdata}\Programs\MediaCatalogVideoDesktop
DefaultGroupName=Media Catalog Video Desktop
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#ReleaseDir}
OutputBaseFilename=MediaCatalogVideoDesktop-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
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

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Media Catalog Video Desktop"; Filename: "{app}\MediaCatalogVideoDesktop.exe"; Check: not IsQAMode
Name: "{autodesktop}\Media Catalog Video Desktop"; Filename: "{app}\MediaCatalogVideoDesktop.exe"; Tasks: desktopicon; Check: not IsQAMode

[Run]
Filename: "{app}\MediaCatalogVideoDesktop.exe"; Description: "Launch Media Catalog Video Desktop"; Flags: nowait postinstall skipifsilent; Check: not IsQAMode

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
