# Oniflow Native Build Guide

The free native build uses Nuitka Community and a self-signed Windows code-signing certificate.

## First-Time Setup

Install Nuitka:

```powershell
.\setup_native_build.ps1
```

Install the free Visual Studio C++ Build Tools when required:

```powershell
.\setup_native_build.ps1 -InstallBuildTools
```

Create a private test-signing certificate:

```powershell
.\create_test_signing_certificate.ps1
```

## Build

Build a native protected release without signing:

```powershell
.\build_native_release.ps1
```

Build and apply the self-signed test signature:

```powershell
.\build_native_release.ps1 -SignFiles
```

Build and sign the installer after the native release is fully tested:

```powershell
.\build_installer.ps1 -SignFiles
```

## Important Limits

- Nuitka Community is free.
- Visual Studio Build Tools are free.
- The self-signed certificate is free and intended only for testing with trusted friends.
- Windows SmartScreen may still warn users because the certificate is not publicly trusted.
- Never export or share the private key of the test-signing certificate.
