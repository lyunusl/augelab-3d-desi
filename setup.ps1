# 3 kamerayla kargo desisi ölçümü — Windows kurulumu (tekrar çalıştırılabilir).
#
#   powershell -ExecutionPolicy Bypass -File setup.ps1 [-Venv C:\yol\venv] [-Python py]
#
# venv kısa bir yolda oluşturulur (varsayılan %USERPROFILE%\venvs\desi3d): derin klasörlerde
# Windows uzun yol sınırı pip kurulumunu bozuyor. git gerekmez; MoGe ve Pi3 zip arşivinden kurulur.
# Gerekenler: Python 3.12 (py başlatıcısı ya da PATH'te python), NVIDIA sürücüsü (CUDA 12.8 uyumlu).

param(
    [string]$Venv = $(if ($env:DESI3D_VENV) { $env:DESI3D_VENV } else { Join-Path $env:USERPROFILE "venvs\desi3d" }),
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"

$UTILS3D_ZIP = "https://github.com/EasternJournalist/utils3d-moge/archive/62f09d58509485564e24d5d9f6aac9ee9ebc0c37.zip"
$MOGE_ZIP    = "https://github.com/microsoft/MoGe/archive/refs/heads/main.zip"
$PI3_ZIP     = "https://github.com/yyfz/Pi3/archive/refs/heads/main.zip"
$TORCH_INDEX = "https://download.pytorch.org/whl/cu128"

function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }

function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Komut başarısız ($LASTEXITCODE): $Exe $($Arguments -join ' ')" }
}

# --- 1. venv ---
$py = Join-Path $Venv "Scripts\python.exe"
if (Test-Path $py) {
    Step "venv zaten var: $Venv"
} else {
    Step "venv oluşturuluyor: $Venv"
    New-Item -ItemType Directory -Force (Split-Path $Venv -Parent) | Out-Null
    if ($Python) {
        Invoke-Checked $Python @("-m", "venv", $Venv)
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        Invoke-Checked "py" @("-3.12", "-m", "venv", $Venv)
    } else {
        Invoke-Checked "python" @("-m", "venv", $Venv)
    }
}
Invoke-Checked $py @("-m", "pip", "install", "--upgrade", "pip")

# --- 2. torch (CUDA 12.8) ---
Step "torch + torchvision (cu128)"
Invoke-Checked $py @("-m", "pip", "install", "torch", "torchvision", "--index-url", $TORCH_INDEX)

# --- 3. MoGe (tek görüntü, MoGe-2) ---
# MoGe'nin kendi bağımlılık listesi gradio, flex-gemm vb. git kaynakları içeriyor; --no-deps ile
# kurulup çalışma anında gerekenler elle eklenir.
Step "utils3d-moge"
Invoke-Checked $py @("-m", "pip", "install", $UTILS3D_ZIP)
Step "MoGe (--no-deps) + çalışma bağımlılıkları"
Invoke-Checked $py @("-m", "pip", "install", "--no-deps", $MOGE_ZIP)
Invoke-Checked $py @("-m", "pip", "install", "click", "opencv-python", "scipy", "matplotlib", "trimesh",
                     "huggingface-hub", "requests", "tqdm", "pillow")

# --- 4. Pi3 / Pi3X (çok açı, sabit kameralar) ---
$src = Join-Path $Venv "src"
$pi3Dir = Join-Path $src "Pi3-main"
if (Test-Path (Join-Path $pi3Dir "pyproject.toml")) {
    Step "Pi3 kaynağı zaten var: $pi3Dir"
} else {
    Step "Pi3 indiriliyor"
    New-Item -ItemType Directory -Force $src | Out-Null
    $zip = Join-Path $src "Pi3-main.zip"
    Invoke-WebRequest -Uri $PI3_ZIP -OutFile $zip -UseBasicParsing
    Expand-Archive -Path $zip -DestinationPath $src -Force
    Remove-Item $zip
}
Step "Pi3 (editable, --no-deps)"
Invoke-Checked $py @("-m", "pip", "install", "--no-deps", "-e", $pi3Dir)

# --- 5. diğerleri ---
Step "rerun-sdk, safetensors, einops, plyfile"
Invoke-Checked $py @("-m", "pip", "install", "rerun-sdk", "safetensors", "einops", "plyfile")

# --- 6. kontrol ---
Step "Kontrol"
Invoke-Checked $py @("-c", "import torch, cv2, moge, pi3; print('torch', torch.__version__, 'CUDA', torch.cuda.is_available()); print('opencv', cv2.__version__, 'aruco', hasattr(cv2, 'aruco'))")

Write-Host @"

Kurulum tamam.  venv: $Venv

Sonraki adımlar:
  1. Servisi başlat:  service\start_server.cmd
     (venv başka yerdeyse önce:  set DESI3D_VENV=$Venv)
     İlk açılışta model ağırlıkları Hugging Face'ten iner: Pi3X ~5,4 GB, MoGe-2 ~1,3 GB
     (yalnızca Tek görüntü modu kullanılınca). "hazır: http://127.0.0.1:8770" satırını bekle.
  2. studio_blocks\*.py dosyalarını şuraya kopyala ve AugeLab Studio'yu yeniden başlat:
     $env:APPDATA\AugeLab Studio\marketplace\custom_blocks\
  3. card\aruco_kart_100mm_A4.pdf dosyasını %100 ölçekle yazdır, siyah kareyi cetvelle kontrol et.
  4. README.md'deki "Studio'da kullanım" adımlarını izle.

Lisans notu: Pi3X ağırlıkları CC BY-NC 4.0 (ticari kullanım yok). Ayrıntı: README.md > Lisanslar.
"@ -ForegroundColor Green
