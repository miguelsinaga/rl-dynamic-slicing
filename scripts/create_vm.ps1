# Buat VM Ubuntu 22.04 Server di VirtualBox untuk testbed. Jalankan di Windows (bukan di dalam VM):
#   powershell -ExecutionPolicy Bypass -File scripts\create_vm.ps1
# Setelah VM menyala: ikuti installer Ubuntu, centang "Install OpenSSH server".
# SSH dari Windows: ssh -p 2222 <user>@127.0.0.1
param(
    [string]$Name = 'sdn-slicing',
    [int]$Cpus = 4,
    [int]$MemoryMB = 6144,
    [int]$DiskMB = 25600,  # dinamis: hanya terpakai sesuai isi (~10 GB setelah setup)
    [string]$Iso = "$env:USERPROFILE\Downloads\ubuntu-22.04.5-live-server-amd64.iso"
)
$ErrorActionPreference = 'Stop'
$vbox = "$env:ProgramFiles\Oracle\VirtualBox\VBoxManage.exe"
$base = 'https://releases.ubuntu.com/jammy'

function Invoke-VBox {
    & $vbox @args
    if ($LASTEXITCODE -ne 0) { throw "VBoxManage $($args -join ' ') gagal" }
}

if ((& $vbox list vms) -match "^`"$Name`" ") { throw "VM '$Name' sudah ada. Hapus dulu atau pakai -Name lain." }

if (-not (Test-Path $Iso)) {
    Write-Host "Mengunduh ISO Ubuntu 22.04.5 (~2 GB) ke $Iso"
    curl.exe -L --fail -o $Iso "$base/ubuntu-22.04.5-live-server-amd64.iso"
    if ($LASTEXITCODE -ne 0) { throw 'Unduh ISO gagal' }
}
$expected = ((curl.exe -sL --fail "$base/SHA256SUMS") | Select-String 'live-server-amd64.iso').ToString().Split(' ')[0]
if ((Get-FileHash $Iso -Algorithm SHA256).Hash -ne $expected) { throw 'Checksum ISO tidak cocok, hapus file ISO lalu ulangi' }

$folder = ((& $vbox list systemproperties | Select-String 'Default machine folder:').ToString() -split ':\s+', 2)[1].Trim()
$disk = Join-Path $folder "$Name\$Name.vdi"

Invoke-VBox createvm --name $Name --ostype Ubuntu22_LTS_64 --register
Invoke-VBox modifyvm $Name --cpus $Cpus --memory $MemoryMB --vram 16 --graphicscontroller vmsvga `
    --nic1 nat --natpf1 'ssh,tcp,127.0.0.1,2222,,22'
Invoke-VBox createmedium disk --filename $disk --size $DiskMB
Invoke-VBox storagectl $Name --name SATA --add sata --controller IntelAhci
Invoke-VBox storageattach $Name --storagectl SATA --port 0 --device 0 --type hdd --medium $disk
Invoke-VBox storageattach $Name --storagectl SATA --port 1 --device 0 --type dvddrive --medium $Iso
Invoke-VBox startvm $Name
Write-Host "VM '$Name' berjalan. Selesaikan installer, lalu: ssh -p 2222 <user>@127.0.0.1"
