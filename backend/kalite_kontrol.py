"""
KampüsSes kalite kontrolü — Faz 2 raporundaki K3 ve K4 kalite kapılarını tek komutla çalıştırır.

Kullanım (backend klasöründe):
    venv\\Scripts\\python kalite_kontrol.py

Her araç sırayla çalışır, çıktısı kalite_raporlari/ klasörüne kaydedilir ve sonunda
her kapı için GEÇTİ / KALDI özeti yazılır. Bir kapı kalırsa komut 1 koduyla biter.

Kapılar ve eşikler (Faz 2 raporu, bölüm 4 ve 6):
    K3  Testler          : tüm testler geçer
    K3  NFR-05a Kapsam   : backend satır kapsamı en az %70 (pyproject.toml: fail_under)
    K4  Ruff             : Ruff hatası 0
    K4  NFR-05b McCabe   : fonksiyon başına karmaşıklık en fazla 10
    K4  Bandit           : yüksek önem dereceli güvenlik bulgusu 0
    K4  pip-audit        : kullanılan paketlerde bilinen güvenlik açığı 0
"""
import os
import platform
# Bandit B404 gerekçesi: yalnızca sabit, projeye ait komutlar çalıştırılır.
import subprocess  # nosec B404
import sys
import tomllib
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
REPORT_DIR = BASE_DIR / "kalite_raporlari"
PY = sys.executable
# Eşikler tek yerde, pyproject.toml'da tutulur.
CONFIG = tomllib.loads((BASE_DIR / "pyproject.toml").read_text(encoding="utf-8"))
COVERAGE_TARGET = CONFIG["tool"]["coverage"]["report"]["fail_under"]
MAX_COMPLEXITY = CONFIG["tool"]["ruff"]["lint"]["mccabe"]["max-complexity"]
# Testlerin sonucu kapsam kapısında da kullanılır.
state = {"tests_ok": False}


def run(args):
    """Komutu kabuk kullanmadan çalıştırır; (çıkış kodu, çıktı) döner."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "NO_COLOR": "1"}
    # Bandit B603 gerekçesi: kabuk kullanılmaz, argümanlar sabit listedir, kullanıcı girdisi yoktur.
    result = subprocess.run(  # nosec B603
        args, cwd=BASE_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env
    )
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def save(name, text):
    (REPORT_DIR / name).write_text(text, encoding="utf-8")


def count_lines(text, marker):
    return sum(1 for line in text.splitlines() if marker in line)


def check_tests():
    run([PY, "-m", "coverage", "erase"])  # Önceki çalıştırmanın kapsam verisi kullanılmasın.
    code, out = run([PY, "-m", "coverage", "run", "manage.py", "test", "--noinput"])
    state["tests_ok"] = code == 0
    save("1_testler.txt", out)
    summary = next((line for line in reversed(out.splitlines()) if line.startswith("Ran ")), "test sonucu okunamadı")
    return code == 0, summary


def check_coverage():
    code, out = run([PY, "-m", "coverage", "report"])
    save("2_kapsam.txt", out)
    _, total = run([PY, "-m", "coverage", "report", "--format=total"])
    if not total.strip().isdigit():  # Testler hiç veri üretmeden çöktüyse.
        return False, f"kapsam ölçülemedi (hedef en az %{COVERAGE_TARGET}); ayrıntı: 2_kapsam.txt"
    detail = f"toplam satır kapsamı %{total.strip()} (hedef en az %{COVERAGE_TARGET})"
    if not state["tests_ok"]:
        # Kalan testlerle ölçülen kapsam güvenilir kanıt sayılmaz.
        return False, detail + " — testler kaldığı için geçersiz"
    return code == 0, detail


def check_ruff():
    code, out = run([PY, "-m", "ruff", "check", ".", "--output-format", "concise", "--statistics"])
    _, detail = run([PY, "-m", "ruff", "check", ".", "--output-format", "concise"])
    save("3_ruff.txt", detail + "\n\nÖzet:\n" + out)
    errors = count_lines(detail, ".py:")
    return code == 0, f"{errors} bulgu (hedef 0)"


def check_complexity():
    code, out = run([PY, "-m", "ruff", "check", ".", "--select", "C901", "--output-format", "concise"])
    save("4_karmasiklik.txt", out)
    too_complex = count_lines(out, "C901")
    return code == 0, f"karmaşıklığı {MAX_COMPLEXITY}'u aşan {too_complex} fonksiyon (hedef 0)"


def check_bandit():
    # Tüm önem dereceleri raporlanır; kapı yalnızca yüksek önemli bulguda kalır (K4).
    _, full = run([PY, "-m", "bandit", "-c", "pyproject.toml", "-r", "."])
    save("5_bandit.txt", full)
    code, _ = run([PY, "-m", "bandit", "-c", "pyproject.toml", "-r", ".", "-q", "--severity-level", "high"])
    counts = {level: count_lines(full, f"Severity: {level}") for level in ("High", "Medium", "Low")}
    return code == 0, f"yüksek {counts['High']}, orta {counts['Medium']}, düşük {counts['Low']} (hedef: yüksek 0)"


def check_pip_audit():
    code, out = run([PY, "-m", "pip_audit", "--progress-spinner", "off"])
    save("6_pip_audit.txt", out)
    rows = [line.split() for line in out.splitlines() if line[:1].isalpha() and len(line.split()) >= 3]
    packages = sorted({row[0] for row in rows if row[0] not in {"Name", "Found", "No"}})
    found = sum(1 for row in rows if row[0] in packages)
    if code == 0:
        return True, "bilinen açık bulunmadı"
    return False, f"{found} bilinen açık; etkilenen paketler: {', '.join(packages) or 'çıktıya bakın'} (hedef 0)"


GATES = [
    ("K3", "Testler", check_tests),
    ("K3", "NFR-05a Test kapsamı", check_coverage),
    ("K4", "Ruff", check_ruff),
    ("K4", "NFR-05b McCabe karmaşıklığı", check_complexity),
    ("K4", "Bandit güvenlik taraması", check_bandit),
    ("K4", "pip-audit paket açıkları", check_pip_audit),
]


def main():
    # Windows konsolu her karakteri gösteremeyebilir; yazdırılamayan karakter yüzünden komut çökmesin.
    sys.stdout.reconfigure(errors="replace")
    REPORT_DIR.mkdir(exist_ok=True)
    try:
        code, commit = run(["git", "rev-parse", "--short", "HEAD"])
        if code != 0:  # Klasör bir git deposu değil.
            commit = "bilinmiyor (git deposu değil)"
    except OSError:  # git kurulu değilse kontrol yine de çalışır.
        commit = "bilinmiyor (git bulunamadı)"
    header = [
        "KampüsSes kalite kontrolü",
        f"Tarih   : {datetime.now():%Y-%m-%d %H:%M}",
        f"Commit  : {commit.strip()} (kaydedilmemiş değişiklikler dahil olabilir)",
        f"Python  : {platform.python_version()} · {platform.system()} {platform.release()}",
        "",
    ]
    print("\n".join(header))

    lines, failed = [], 0
    for gate, name, check in GATES:
        print(f"Çalışıyor: {name} ...", flush=True)
        ok, detail = check()
        failed += not ok
        lines.append(f"[{'GEÇTİ' if ok else 'KALDI'}] {gate} · {name}: {detail}")

    lines.append("")
    lines.append("SONUÇ: " + ("Tüm kapılar geçti." if not failed else f"{failed} kapı kaldı."))
    # Bilgisayardaki tam yol (kullanıcı adı dahil) rapora yazılmaz.
    lines.append(f"Ayrıntılar: backend/{REPORT_DIR.name}/ klasörü")
    print("\n" + "\n".join(lines))
    save("0_ozet.txt", "\n".join(header + lines) + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
