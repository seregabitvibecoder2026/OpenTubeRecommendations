{
  description = "OpenTubeRecommendations dev shell (kept in ./nix so nix does not copy data/ and .venv into the store)";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAll = f: nixpkgs.lib.genAttrs systems (s: f (import nixpkgs { system = s; config.allowUnfree = false; }));
    in {
      devShells = forAll (pkgs: { default = import ./devshell.nix { inherit pkgs; }; });
    };
}
