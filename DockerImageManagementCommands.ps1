# Build, tag and push a release to Docker Hub.
#
# Usage:  .\DockerImageManagementCommands.ps1              # version read from the Dockerfile
#         .\DockerImageManagementCommands.ps1 -SkipBuild   # push an image already built
#         .\DockerImageManagementCommands.ps1 -WhatIf      # print what would run
#
# Previously these were three bare commands that tagged and pushed whatever
# photo-moderation:latest happened to be lying around locally, with the version typed in
# by hand and `push --all-tags` sending every local tag of the repository.

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$Repository = 'mcoopergb/photo-moderation',
    [string]$LocalImage = 'photo-moderation:latest',
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Invoke-Docker {
    param([Parameter(Mandatory)][string[]]$Arguments)

    Write-Host "docker $($Arguments -join ' ')" -ForegroundColor Cyan
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

Push-Location $PSScriptRoot
try {
    # Single source of truth for the version: the Dockerfile label. Keeping a copy here
    # is how the tag and the image metadata drift apart.
    $dockerfile = Join-Path $PSScriptRoot 'Dockerfile'
    $versionMatch = Select-String -Path $dockerfile `
        -Pattern '^LABEL\s+org\.opencontainers\.image\.version="([^"]+)"' |
        Select-Object -First 1

    if ($null -eq $versionMatch) {
        throw "Could not read org.opencontainers.image.version from $dockerfile"
    }

    $version = $versionMatch.Matches[0].Groups[1].Value
    Write-Host "Releasing version $version to $Repository" -ForegroundColor Green

    if (-not $SkipBuild) {
        # --pull and a fresh SECURITY_REFRESH so the base image and the apt-get upgrade
        # layer are not served from a stale cache. See the Dockerfile comment.
        $refresh = Get-Date -Format 'yyyy-MM-dd'
        if ($PSCmdlet.ShouldProcess($LocalImage, 'docker build')) {
            Invoke-Docker @('build', '--pull',
                            '--build-arg', "SECURITY_REFRESH=$refresh",
                            '-t', $LocalImage, '.')
        }
    }
    else {
        # Fail early rather than tagging a name that does not resolve. Windows PowerShell
        # turns a native command's redirected stderr into a terminating error while
        # $ErrorActionPreference is 'Stop', so relax it here and read the exit code.
        $exists = $(
            $ErrorActionPreference = 'Continue'
            & docker image inspect $LocalImage *> $null
            $LASTEXITCODE -eq 0
        )
        if (-not $exists) {
            throw "$LocalImage is not present locally; drop -SkipBuild to build it"
        }
    }

    # Push the two tags explicitly. --all-tags would also republish every other local
    # tag of this repository, including stale ones from earlier releases.
    # The published tags are v-prefixed (v1.2.0, v1.2.1); the Dockerfile label is not.
    foreach ($tag in @("$Repository`:v$version", "$Repository`:latest")) {
        if ($PSCmdlet.ShouldProcess($tag, 'docker tag and push')) {
            Invoke-Docker @('tag', $LocalImage, $tag)
            Invoke-Docker @('push', $tag)
        }
    }

    Write-Host "Pushed $Repository`:v$version and $Repository`:latest" -ForegroundColor Green
}
finally {
    Pop-Location
}
