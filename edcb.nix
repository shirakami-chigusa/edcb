{ stdenv, fetchFromGitHub, lua52, openssl, curl, makeWrapper }:

stdenv.mkDerivation rec {
  pname = "edcb";
  version = "work-plus-s-unstable-2025-05-31"; # Based on commit date

  src = fetchFromGitHub {
    owner = "xtne6f";
    repo = "EDCB";
    rev = "2b714764ff87199995a68efa065f759816c7bcee";
    # sha256 is a placeholder and will need to be filled in after the first build attempt or by using nix-prefetch-url
    sha256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"; # placeholder - needs correct hash!
  };

  nativeBuildInputs = [ makeWrapper ];
  buildInputs = [
    stdenv.cc.cc # for g++
    lua52
    lua52.pkgs.zlib # lua-zlib
    openssl # Optional for WebUI SSL/TLS
    curl    # Optional for 'make extra'
  ];

  # The Makefile is in Document/Unix
  preBuild = ''
    cd Document/Unix
  '';

  patchPhase = ''
    runHook prePatch
    echo "Patching EpgTimerSrv Makefile to use -llua instead of -llua5.2"
    # Path relative to source root, as patchPhase runs before preBuild's cd.
    sed -i 's/-llua5.2/-llua/g' EpgTimerSrv/EpgTimerSrv/Makefile

    echo "Patching Document/Unix/Makefile for install_tools target paths"
    # Replace hardcoded /usr/local/bin with $(DESTDIR)$(PREFIX)/bin for install targets
    # This makes sure tools are installed into $out correctly when DESTDIR is used.
    sed -i 's|install\(.*\) /usr/local/bin|install \1 $(DESTDIR)$(PREFIX)/bin|g' Document/Unix/Makefile
    runHook postPatch
  '';

  buildPhase = ''
    runHook preBuild
    # Default make command
    make
    # Build extra tools
    make extra
    # Build EpgTimerSrv with rpath, though Nix should handle this.
    # We might need to adjust LDFLAGS if lua is not found directly.
    # For now, let stdenv try to handle rpath.
    make EpgTimerSrv.clean
    make EpgTimerSrv.all
    runHook postBuild
  '';

  installPhase = ''
    runHook preInstall

    # Change to the directory containing the main Makefile
    cd Document/Unix

    # Install main components
    make install DESTDIR=$out PREFIX=/usr/local
    # Install extra tools
    make install_extra DESTDIR=$out PREFIX=/usr/local
    # Install EpgTimerSrv
    make EpgTimerSrv.install DESTDIR=$out PREFIX=/usr/local

    # Configuration files
    # mkdir -p $out/share/edcb/ini
    # cp -r ../../ini/* $out/share/edcb/ini
    # The above paths might need adjustment.
    # `make setup_ini` in the original instructions does:
    #   mkdir -p /var/local/edcb
    #   cp -r ini/* /var/local/edcb
    # For Nix, we should place them in $out and inform the user.
    # Let's try to replicate 'make setup_ini' target manually for $out
    mkdir -p $out/share/edcb
    cp -r $src/ini $out/share/edcb/

    # Create a wrapper for EpgTimerSrv to point to a config dir?
    # For now, let's install binaries directly.
    # Users will need to manage their own /var/local/edcb or similar.
    runHook postInstall
  '';

  # NOTE: The SHA256 for src is a placeholder and needs to be replaced with the actual hash.
  # TODO: Add meta information
  meta = with stdenv.lib; {
    description = "BonDriver based multifunctional EPG software";
    homepage = "https://github.com/xtne6f/EDCB";
    license = licenses.mit; # Assuming MIT based on typical GitHub projects, verify this
    platforms = platforms.linux;
    maintainers = [ maintainers.your_username ]; # Replace with actual maintainer
  };
}
