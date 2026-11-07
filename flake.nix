{
  description = "credit-scanner: analyze Abacus.AI credit usage in saved transcript files";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
      forAll = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      packages = forAll (pkgs: {
        default = pkgs.stdenvNoCC.mkDerivation {
          pname = "credit-scanner";
          version = "1.0.0";
          src = ./.;
          nativeBuildInputs = [ pkgs.makeWrapper ];
          dontBuild = true;
          installPhase = ''
            runHook preInstall
            install -Dm755 credit-scanner.sh $out/bin/credit-scanner
            patchShebangs $out/bin/credit-scanner
            wrapProgram $out/bin/credit-scanner \
              --prefix PATH : ${pkgs.lib.makeBinPath [ pkgs.gawk pkgs.coreutils pkgs.gnugrep ]}
            runHook postInstall
          '';
          meta = {
            description = "Analyze Abacus.AI credit usage in saved transcript files";
            homepage = "https://github.com/entropytwo-ai/abacusai-transcript-credit-analysis";
            license = pkgs.lib.licenses.gpl3Plus;
            mainProgram = "credit-scanner";
          };
        };
      });

      apps = forAll (pkgs: {
        default = {
          type = "app";
          program = "${self.packages.${pkgs.system}.default}/bin/credit-scanner";
        };
      });

      devShells = forAll (pkgs: {
        default = pkgs.mkShell {
          packages = with pkgs; [ bash gawk mawk busybox shellcheck gnumake ];
        };
      });
    };
}
