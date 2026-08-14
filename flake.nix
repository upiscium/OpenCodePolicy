{
  description = "Shared OpenCode policy contracts and read-only consumer audit tooling";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
      packageFor = system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        pkgs.stdenvNoCC.mkDerivation {
          pname = "opencode-policy";
          version = "unstable";
          src = self;
          nativeBuildInputs = [ pkgs.makeWrapper ];
          dontBuild = true;
          installPhase = ''
            runHook preInstall
            mkdir -p "$out/share/opencode-policy" "$out/bin"
            cp -r policy profiles tools "$out/share/opencode-policy/"
            makeWrapper ${pkgs.python3}/bin/python3 "$out/bin/opencode-policy" \
              --add-flags "$out/share/opencode-policy/tools/opencode_policy.py"
            runHook postInstall
          '';
        };
    in
    {
      packages = forAllSystems (system:
        let package = packageFor system;
        in {
          default = package;
          "opencode-policy" = package;
        });

      apps = forAllSystems (system: {
        default = {
          type = "app";
          program = "${packageFor system}/bin/opencode-policy";
          meta.description = "Validate OpenCode policy and audit explicitly selected consumers";
        };
      });

      checks = forAllSystems (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          package = packageFor system;
        in {
          policy = pkgs.runCommand "opencode-policy-validation" {
            nativeBuildInputs = [ package ];
          } ''
            opencode-policy validate
            touch "$out"
          '';

          audit-consumer = pkgs.runCommand "opencode-policy-packaged-audit" {
            nativeBuildInputs = [ package pkgs.python3 ];
          } ''
            cp -r ${self}/policy ${self}/profiles ${self}/tools ${self}/tests .
            chmod -R u+w policy profiles tools tests
            python3 - <<'PY'
            from pathlib import Path
            from tests.test_cli import ConsumerAuditCliTest

            ConsumerAuditCliTest.setUpClass()
            case = ConsumerAuditCliTest(methodName="test_validate_command")
            case.make_consumer(Path("fixture"), "global")
            case.make_consumer(Path("fixture"), "agent-core")
            PY
            chmod -R a-w fixture
            opencode-policy audit-consumer --profile global --consumer "$PWD/fixture/global" --strict
            opencode-policy audit-consumer --profile agent-core --consumer "$PWD/fixture/agent-core" --strict
            touch "$out"
          '';

          tests = pkgs.runCommand "opencode-policy-tests" {
            nativeBuildInputs = [ pkgs.python3 ];
          } ''
            cp -r ${self}/policy ${self}/profiles ${self}/tools ${self}/tests .
            chmod -R u+w policy profiles tools tests
            python3 -m unittest discover -s tests -v
            touch "$out"
          '';
        });

      devShells = forAllSystems (system:
        let pkgs = nixpkgs.legacyPackages.${system};
        in {
          default = pkgs.mkShell {
            packages = [ pkgs.python3 ];
          };
        });
    };
}
