# Setup Huawei Cloud ECS untuk testbed

Panduan ini menyiapkan satu server Ubuntu 22.04 di Huawei Cloud (ECS) yang bisa kamu buka dari
VS Code, lalu memasang semua yang dibutuhkan proyek (Mininet, Open vSwitch, Ryu, PyTorch).

- **Hasil akhir:** `ssh sdn-ecs` dari laptop berhasil, dan smoke test di ECS menampilkan `SEMUA LULUS`.
- **Waktu:** ±45 menit. Sebagian besar menunggu instalasi.
- **Biaya:** 0 kalau memakai ECS free trial. Baca bagian 8 sebelum menaikkan spek.

Perintah laptop di bawah ditulis untuk Windows (PowerShell). Untuk macOS/Linux ada catatan singkat
di tiap langkah.

---

## 0. Yang perlu disiapkan

- Akun Huawei Cloud yang sudah terverifikasi (real-name / metode pembayaran terpasang).
- VS Code dengan extension **Remote - SSH** (dari Microsoft).
- OpenSSH di laptop. Windows 10/11 sudah punya; cek dengan `ssh -V` di PowerShell.

Jangan pernah membagikan **password akun** atau **private key** ke siapa pun, termasuk lewat chat
atau ke AI assistant. Yang boleh dibagikan hanya *public key* (file `.pub`).

---

## 1. Buat SSH key di laptop

Key ini dipakai untuk login ke ECS tanpa password. Satu orang, satu key.

```powershell
ssh-keygen -t rsa -b 4096 -f $HOME\.ssh\huawei_ecs -C sdn-ecs
```

Saat diminta passphrase, boleh dikosongkan (tekan Enter dua kali) atau diisi. Hasilnya dua file:

| File | Isi | Boleh dibagikan? |
|---|---|---|
| `C:\Users\<kamu>\.ssh\huawei_ecs` | private key | **Tidak** |
| `C:\Users\<kamu>\.ssh\huawei_ecs.pub` | public key | Ya |

Tampilkan public key untuk langkah 3:

```powershell
Get-Content $HOME\.ssh\huawei_ecs.pub
```

> macOS/Linux: `ssh-keygen -t rsa -b 4096 -f ~/.ssh/huawei_ecs -C sdn-ecs` lalu `cat ~/.ssh/huawei_ecs.pub`.

---

## 2. Catat IP publik laptop

Security group nanti hanya mengizinkan SSH dari IP ini.

```powershell
Invoke-RestMethod https://api.ipify.org
```

Catat hasilnya, misalnya `182.10.x.x`. IP ini bisa berubah kalau kamu ganti WiFi atau modem
restart; lihat bagian 9 kalau SSH tiba-tiba tidak bisa.

---

## 3. Impor key pair di console

1. Login ke console Huawei Cloud.
2. Pilih region di kiri atas: **AP-Jakarta**. Kalau free trial tidak tersedia di Jakarta, pakai
   **AP-Singapore**. Key pair terikat ke region, jadi region di sini harus sama dengan region ECS.
3. Elastic Cloud Server → **Key Pair** → **Import Key Pair**.
4. Name: `sdn-ecs`. Public Key: tempel satu baris penuh hasil `Get-Content` di langkah 1
   (diawali `ssh-rsa`, diakhiri `sdn-ecs`).

---

## 4. Klaim ECS free trial

Buka halaman **Free Trial / Free Packages** Huawei Cloud, pilih penawaran Elastic Cloud Server, lalu isi:

| Bagian | Pilihan |
|---|---|
| Region | Sama dengan langkah 3 (AP-Jakarta atau AP-Singapore) |
| Flavor | Yang gratis (General computing S6, 1 vCPU) |
| Image | Public image → **Ubuntu 22.04 server 64bit** |
| System disk | 40 GB (default) |
| Network | VPC dan subnet default |
| EIP | **Wajib ada** (auto assign). Tanpa EIP, ECS tidak bisa diakses dari laptop |
| Security group | Buat baru. Inbound: **TCP 22, source `<IP-dari-langkah-2>/32`**. Hapus aturan inbound lain (mis. 3389, ICMP dari 0.0.0.0/0) |
| Login mode | **Key pair** → `sdn-ecs` |
| Name | `sdn-ecs` |

Sebelum menekan konfirmasi:
- Ringkasan biaya harus 0. Perhatikan apakah EIP ditagih terpisah.
- Pastikan instance **tidak otomatis menjadi berbayar** setelah masa trial habis.

Tunggu sampai status ECS **Running**, lalu catat EIP (IP publik ECS) dari daftar instance.

> Jangan buka port 6640, 6653, atau 8080 di security group. Ryu dan OVSDB sengaja hanya
> mendengarkan di `127.0.0.1` di dalam ECS.

---

## 5. Sambungkan dari laptop

Tambahkan blok ini ke file `C:\Users\<kamu>\.ssh\config` (buat file baru kalau belum ada,
tanpa ekstensi):

```
Host sdn-ecs
    HostName <EIP>
    User root
    IdentityFile ~/.ssh/huawei_ecs
```

Tes dari PowerShell:

```powershell
ssh sdn-ecs
```

Pertama kali akan muncul pertanyaan `Are you sure you want to continue connecting`. Ketik `yes`.
Kalau prompt berubah menjadi `root@sdn-ecs:~#`, berhasil. Keluar dengan `exit`.

Di VS Code: `Ctrl+Shift+P` → **Remote-SSH: Connect to Host** → `sdn-ecs` → pilih **Linux**.
Semua langkah berikut dijalankan di terminal VS Code yang sudah terhubung ke ECS.

---

## 6. Pasang semua kebutuhan di ECS

```bash
git clone https://github.com/miguelsinaga/rl-dynamic-slicing.git
cd rl-dynamic-slicing
bash scripts/setup_vm.sh
```

Skrip ini (±20 menit di 1 vCPU):
1. Mengecek kernel (`scripts/check_kernel.sh`): modul `openvswitch`, `sch_htb`, `tcp_bbr`, `veth`.
   Kalau ada `[FAIL]`, skrip berhenti dan mencetak perintah perbaikannya.
2. Memasang Mininet, Open vSwitch, iperf3, Python 3.9.
3. Mengatur kernel sesuai slide (BBR, `netdev_max_backlog`).
4. Membuat `.venv-ryu` (Ryu) dan `.venv-agent` (PyTorch CPU, numpy, dst).
5. Menjalankan pengecekan akhir, termasuk `mn --test pingall`.

Kalau repo private, `git clone` akan meminta username GitHub dan **personal access token**
(bukan password GitHub). Buat token di GitHub → Settings → Developer settings → Personal access tokens.

---

## 7. Smoke test

Proses yang berjalan lama sebaiknya dijalankan di dalam tmux, supaya tidak mati kalau
koneksi SSH putus.

```bash
tmux new -s sdn
```

Di tmux, buka dua panel: `Ctrl+b` lalu `%` (bagi kiri-kanan). Pindah panel dengan `Ctrl+b` lalu panah.

Panel kiri, controller:

```bash
cd ~/rl-dynamic-slicing
.venv-ryu/bin/ryu-manager --wsapi-host 127.0.0.1 controller/slicing_app.py
```

Panel kanan, smoke test:

```bash
cd ~/rl-dynamic-slicing
sudo .venv-agent/bin/python -m experiments.smoke_test
```

Hasil yang diharapkan: semua baris `[PASS]`, diakhiri `SEMUA LULUS`. Kalau ada `[FAIL]`,
salin seluruh output smoke test dan log Ryu ke grup.

Keluar dari tmux tanpa mematikan proses: `Ctrl+b` lalu `d`. Masuk lagi: `tmux attach -t sdn`.

---

## 8. Spek: kapan 1 vCPU cukup

| Pekerjaan | 1 vCPU (gratis) | 4 vCPU / 8 GiB |
|---|---|---|
| Setup, smoke test, debugging | Cukup | |
| Training PPO (`agent.train`) | | **Wajib** |
| Eksperimen final (`experiments.run_all`) | | **Wajib** |

Alasannya: latency URLLC diukur oleh proses Python di dalam ECS. Di 1 vCPU, sekitar 18 proses trafik
berebut satu core, sehingga delay yang tercatat ikut memasukkan antrean CPU (beberapa ms), padahal
ambang URLLC hanya 5 ms. Angka training dan eksperimen jadi tidak valid.

Untuk sesi training/eksperimen (±3–4 jam total): matikan ECS → **More → Modify Specifications** →
pilih 4 vCPU | 8 GiB → nyalakan lagi. Disk dan isinya tetap. Instance trial kadang tidak boleh
diubah speknya; kalau begitu, buat ECS pay-per-use baru dengan langkah 3–6 yang sama.
Setelah selesai, kembalikan ke spek kecil atau hapus ECS-nya.

---

## 9. Kalau ada masalah

| Gejala | Penyebab umum | Solusi |
|---|---|---|
| `Connection timed out` | IP laptop berubah, atau EIP belum terpasang | Cek IP (langkah 2), perbarui aturan TCP 22 di security group |
| `Permission denied (publickey)` | Key pair di ECS bukan `sdn-ecs`, atau `User` bukan `root` | Cek login mode ECS dan blok `~/.ssh/config` |
| `UNPROTECTED PRIVATE KEY FILE` (Windows) | Izin file key terlalu longgar | `icacls $HOME\.ssh\huawei_ecs /inheritance:r /grant:r "${env:USERNAME}:R"` |
| `Could not get lock /var/lib/dpkg/lock-frontend` | Ubuntu sedang update otomatis setelah boot pertama | Tunggu 5–10 menit, lalu ulangi `bash scripts/setup_vm.sh` |
| `check_kernel.sh` menampilkan `[FAIL]` | Kernel image tanpa modul OVS/HTB | Jalankan perintah yang dicetak skrip, `sudo reboot`, lalu ulangi langkah 6 |
| Smoke test: `pingall gagal` | Ryu belum jalan | Jalankan Ryu dulu di panel kiri (langkah 7) |
| Sisa run sebelumnya mengganggu | QoS/Mininet lama masih ada | `sudo bash scripts/cleanup.sh` |

---

## 10. Memakai satu ECS bersama tim

- Pemilik ECS menambahkan public key teman ke ECS:
  `echo "<isi huawei_ecs.pub teman>" >> /root/.ssh/authorized_keys`
- Teman cukup mengikuti langkah 1 dan 5 (pakai EIP yang sama), lalu pemilik menambahkan IP teman
  ke aturan TCP 22 di security group.
- **Jalankan eksperimen bergantian.** Dua Mininet sekaligus di satu ECS akan bentrok (nama switch dan port sama).

## 11. Biaya dan keamanan

- Matikan (**Stop**) ECS saat tidak dipakai. Disk dan EIP tetap ditagih walau ECS mati, kecuali termasuk trial.
- Setelah proyek selesai: **Delete** ECS dan **Release** EIP.
- Jangan commit file key (`huawei_ecs`, `*.pem`), token GitHub, atau Access Key ke repo.
