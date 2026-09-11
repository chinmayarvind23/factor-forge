#!/bin/sh
# Compile only the original fixed algorithm against the reviewed patched output.
set -eu
dotnet restore FactorForge.LeanSpike.csproj --configfile /recipe/NuGet.Config --verbosity minimal
dotnet build FactorForge.LeanSpike.csproj --configuration Release --no-restore \
  --disable-build-servers -m:2 -p:UseSharedCompilation=false -nodeReuse:false \
  --nologo --verbosity minimal --output /output/algorithm
