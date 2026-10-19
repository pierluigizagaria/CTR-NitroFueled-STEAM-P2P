param([Parameter(Mandatory=$true)][string]$Path)
$ErrorActionPreference = 'Stop'
$signature = Get-AuthenticodeSignature -LiteralPath $Path
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Valve Corp\.') {
    throw 'The pinned Steam runtime must retain its valid Valve Authenticode signature.'
}
Write-Output 'Verified original Valve Steam runtime signature.'
