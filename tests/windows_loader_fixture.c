/* A real import makes successful loading depend on the adjacent sidecar DLL. */
__declspec(dllimport) int bridge_loader_sidecar_value(void);

__declspec(dllexport) int bridge_loader_fixture_value(void) {
    return bridge_loader_sidecar_value();
}
