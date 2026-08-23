# nix/hermes-agent.nix — Overridable Hermes Agent package
#
# callPackage auto-wires nixpkgs args; flake inputs are passed explicitly.
# Users override via:
#   pkgs.hermes-agent.override { extraPythonPackages = [...]; }
#   pkgs.hermes-agent.override { extraDependencyGroups = [ "hindsight" ]; }
{
  lib,
  stdenv,
  makeWrapper,
  callPackage,
  python312,
  nodejs_22,
  ripgrep,
  git,
  openssh,
  ffmpeg,
  tirith,
  # Flake inputs — passed explicitly by packages.nix and overlays.nix
  uv2nix,
  pyproject-nix,
  pyproject-build-systems,
  npm-lockfile-fix,
  # Locked git revision of the flake source — embedded so banner.py can
  # check for updates without needing a local .git directory. Null for
  # impure / dirty builds where flakes can't determine a rev.
  rev ? null,
  # Overridable parameters
  extraPythonPackages ? [ ],
  extraDependencyGroups ? [ ],
}:
let
  nodejs = nodejs_22;

  # The `dfy` extra pulls dfy-intel from the PRIVATE github.com/gleim/dfy
  # repo. Docker/Railway builds receive a GH_TOKEN and can clone it, but the
  # Nix CI build (nix flake check / nix build) runs with no credentials and
  # dies with "Failed to fetch git repository 'https://github.com/gleim/dfy.git'".
  # dfy is an optional extra that self-disables when the package is absent, so
  # the Nix venv is built with every extra that `all` aggregates EXCEPT `dfy`.
  #
  # The list is derived from pyproject.toml's `all` extra (rather than
  # hardcoded) so it can't drift when extras are added/removed there, then
  # intersected with the extras actually recorded in uv.lock. That intersection
  # matters: empty extras such as `cron` (`cron = []`, kept only for back-compat)
  # are not recorded in the lock, and passing one to uv2nix fails with
  # "Extra/group name '...' does not match either extra or dependency group".
  # Callers that DO have credentials can still opt back in via
  # `.override { extraDependencyGroups = [ "dfy" ]; }`.
  lockedExtras =
    let
      lock = fromTOML (builtins.readFile ../uv.lock);
      hermesPkgs = builtins.filter (p: p.name == "hermes-agent") lock.package;
    in
    if hermesPkgs == [ ] then
      [ ]
    else
      builtins.attrNames ((builtins.head hermesPkgs).optional-dependencies or { });

  allSelfRefExtras =
    let
      allDeps = (fromTOML (builtins.readFile ../pyproject.toml)).project.optional-dependencies.all;
      # Turn a self-referential dep like "hermes-agent[cron]" into "cron";
      # anything that isn't a self-reference maps to null and is dropped.
      extractName = dep:
        if lib.hasPrefix "hermes-agent[" dep && lib.hasSuffix "]" dep then
          lib.removeSuffix "]" (lib.removePrefix "hermes-agent[" dep)
        else
          null;
    in
    lib.filter (n: n != null) (map extractName allDeps);

  nixDependencyGroups =
    lib.filter (n: n != "dfy" && builtins.elem n lockedExtras) allSelfRefExtras;

  hermesVenv = callPackage ./python.nix {
    inherit uv2nix pyproject-nix pyproject-build-systems;
    dependency-groups = nixDependencyGroups ++ extraDependencyGroups;
  };

  hermesNpmLib = callPackage ./lib.nix {
    inherit npm-lockfile-fix nodejs;
  };

  hermesTui = callPackage ./tui.nix {
    inherit hermesNpmLib;
  };

  hermesWeb = callPackage ./web.nix {
    inherit hermesNpmLib;
  };

  bundledSkills = lib.cleanSourceWith {
    src = ../skills;
    filter = path: _type: !(lib.hasInfix "/index-cache/" path);
  };

  # Import bundled plugins (memory, context_engine, platforms/*).  Keeping
  # them out of the Python site-packages keeps import semantics identical
  # to a dev checkout — the loader reads them from HERMES_BUNDLED_PLUGINS.
  bundledPlugins = lib.cleanSourceWith {
    src = ../plugins;
    filter = path: _type: !(lib.hasInfix "/__pycache__/" path);
  };

  runtimeDeps = [
    nodejs
    ripgrep
    git
    openssh
    ffmpeg
    tirith
  ];

  runtimePath = lib.makeBinPath runtimeDeps;

  sitePackagesPath = python312.sitePackages;

  # Walk propagatedBuildInputs to include transitive Python deps in PYTHONPATH.
  # Without this, a plugin listing e.g. requests as a dep would fail at runtime
  # if requests isn't already in the sealed uv2nix venv.
  allExtraPythonPackages = python312.pkgs.requiredPythonModules extraPythonPackages;

  pythonPath = lib.makeSearchPath sitePackagesPath allExtraPythonPackages;

  pyprojectHash = builtins.hashString "sha256" (builtins.readFile ../pyproject.toml);
  uvLockHash =
    if builtins.pathExists ../uv.lock then
      builtins.hashString "sha256" (builtins.readFile ../uv.lock)
    else
      "none";
  checkPackageCollisions = ''
    import pathlib, sys, re

    def canonical(name):
        return re.sub(r'[-_.]+', '-', name).lower()

    # Collect core venv package names
    core = set()
    venv_sp = pathlib.Path('${hermesVenv}/${sitePackagesPath}')
    for di in venv_sp.glob('*.dist-info'):
        meta = di / 'METADATA'
        if meta.exists():
            for line in meta.read_text().splitlines():
                if line.startswith('Name:'):
                    core.add(canonical(line.split(':', 1)[1].strip()))
                    break

    # Check each extra package for collisions
    extras_dirs = [${lib.concatMapStringsSep ", " (p: "'${toString p}'") allExtraPythonPackages}]
    for edir in extras_dirs:
        sp = pathlib.Path(edir) / '${sitePackagesPath}'
        if not sp.exists():
            continue
        for di in sp.glob('*.dist-info'):
            meta = di / 'METADATA'
            if not meta.exists():
                continue
            for line in meta.read_text().splitlines():
                if line.startswith('Name:'):
                    pkg = canonical(line.split(':', 1)[1].strip())
                    if pkg in core:
                        print(f'ERROR: plugin package \"{pkg}\" collides with a package in hermes sealed venv', file=sys.stderr)
                        print(f'  from: {di}', file=sys.stderr)
                        print(f'  Remove this dependency from extraPythonPackages.', file=sys.stderr)
                        sys.exit(1)
                    break

    print('No collisions found.')
  '';
in
stdenv.mkDerivation {
  pname = "hermes-agent";
  version = (fromTOML (builtins.readFile ../pyproject.toml)).project.version;

  dontUnpack = true;
  dontBuild = true;
  nativeBuildInputs = [ makeWrapper ];

  installPhase = ''
    runHook preInstall

    mkdir -p $out/share/hermes-agent $out/bin
    cp -r ${bundledSkills} $out/share/hermes-agent/skills
    cp -r ${bundledPlugins} $out/share/hermes-agent/plugins
    cp -r ${hermesWeb} $out/share/hermes-agent/web_dist

    mkdir -p $out/ui-tui
    cp -r ${hermesTui}/lib/hermes-tui/* $out/ui-tui/

    ${lib.concatMapStringsSep "\n"
      (name: ''
        makeWrapper ${hermesVenv}/bin/${name} $out/bin/${name} \
          --suffix PATH : "${runtimePath}" \
          --set HERMES_BUNDLED_SKILLS $out/share/hermes-agent/skills \
          --set HERMES_BUNDLED_PLUGINS $out/share/hermes-agent/plugins \
          --set HERMES_WEB_DIST $out/share/hermes-agent/web_dist \
          --set HERMES_TUI_DIR $out/ui-tui \
          --set HERMES_PYTHON ${hermesVenv}/bin/python3 \
          --set HERMES_NODE ${lib.getExe nodejs} \
          ${lib.optionalString (rev != null) ''--set HERMES_REVISION ${rev} \''}
          ${lib.optionalString (extraPythonPackages != [ ]) ''--suffix PYTHONPATH : "${pythonPath}"''}
      '')
      [
        "hermes"
        "hermes-agent"
        "hermes-acp"
      ]
    }

    ${lib.optionalString (extraPythonPackages != [ ]) ''
      echo "=== Checking for plugin/core package collisions ==="
      ${hermesVenv}/bin/python3 -c "${checkPackageCollisions}"
      echo "=== No collisions ==="
    ''}

    runHook postInstall
  '';

  passthru = {
    inherit
      hermesTui
      hermesWeb
      hermesNpmLib
      hermesVenv
      ;

    devShellHook = ''
      STAMP=".nix-stamps/hermes-agent"
      STAMP_VALUE="${pyprojectHash}:${uvLockHash}"
      if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$STAMP_VALUE" ]; then
        echo "hermes-agent: installing Python dependencies..."
        uv venv .venv --python ${python312}/bin/python3 2>/dev/null || true
        source .venv/bin/activate
        uv pip install -e ".[all]"
        [ -d mini-swe-agent ] && uv pip install -e ./mini-swe-agent 2>/dev/null || true
        mkdir -p .nix-stamps
        echo "$STAMP_VALUE" > "$STAMP"
      else
        source .venv/bin/activate
        export HERMES_PYTHON=${hermesVenv}/bin/python3
      fi
    '';
  };

  meta = with lib; {
    description = "AI agent with advanced tool-calling capabilities";
    homepage = "https://github.com/NousResearch/hermes-agent";
    mainProgram = "hermes";
    license = licenses.mit;
    platforms = platforms.unix;
  };
}
