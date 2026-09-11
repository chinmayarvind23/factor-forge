#!/bin/sh
# Build and execute only the original compression diagnostic; never start LEAN.
set -eu
dotnet restore CompatibilityChecks.csproj --configfile /recipe/NuGet.Config --verbosity minimal
dotnet build CompatibilityChecks.csproj --configuration Release --no-restore \
  --disable-build-servers -m:2 -p:UseSharedCompilation=false -nodeReuse:false \
  --nologo --verbosity minimal --output /output/bin
cp /runtime/*.dll /output/bin/
dotnet /output/bin/CompatibilityChecks.dll
