# Shared dev shell definition (used by ../flake.nix and ./flake.nix).
{ pkgs }:
let
  libs = with pkgs; [ stdenv.cc.cc.lib zlib glib libGL ];
in
pkgs.mkShell {
  packages = with pkgs; [ python312 uv yt-dlp ffmpeg-headless deno git curl ];
  shellHook = ''
    export UV_PYTHON=${pkgs.python312}/bin/python3
    export UV_PYTHON_DOWNLOADS=never
    # Manylinux wheels (numpy, torch, ctranslate2) need these on NixOS;
    # /run/opengl-driver/lib provides the NVIDIA driver (libcuda) for CUDA wheels.
    export LD_LIBRARY_PATH=${pkgs.lib.makeLibraryPath libs}:/run/opengl-driver/lib''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
  '';
}
