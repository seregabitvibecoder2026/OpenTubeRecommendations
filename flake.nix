{
  description = "OpenTubeRecommendations — local anonymous YouTube feed recommender";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAll = f: nixpkgs.lib.genAttrs systems (s: f (import nixpkgs { system = s; config.allowUnfree = false; }));
    in {
      # Note: `./start` uses ./nix/flake.nix (same shell) to avoid copying data/ into the store.
      devShells = forAll (pkgs: { default = import ./nix/devshell.nix { inherit pkgs; }; });
    };
}
