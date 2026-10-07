---
tags: [hardware, raspberry, setup]
---

# Raspberry Pi — configuración

Una de las dos plataformas soportadas; la otra es [[Mini-PC-Setup]], que es la de referencia.
Ver [[ADR-013-Plataforma-Agnostica]].

## Modelo

| Modelo | Veredicto |
|---|---|
| Pi 5 (4/8 GB) | **Recomendado.** ~2× GPU de la Pi 4, 1080p60 cómodo |
| Pi 4 (4 GB) | Viable. Objetivo del [[Presupuesto-de-Rendimiento]] |
| Pi 3 / Zero 2 | No. Sin GLES 3.1 útil ni fillrate |

Almacenamiento: **SSD USB o tarjeta A2 de marca**. La SD barata muere por escrituras — ver regla de debounce en [[ADR-004-SQLite]].
Alimentación: fuente oficial. El brownout se manifiesta como frames perdidos y corrupción de SD, no como apagón.

## Sistema

Raspberry Pi OS **Bookworm 64-bit Lite** (sin escritorio).

`/boot/firmware/config.txt`:
```ini
dtoverlay=vc4-kms-v3d
gpu_mem=256              # relevante en Pi 4; en Pi 5 la memoria es unificada
hdmi_force_hotplug=1     # proyector apagado al bootear -> igual saca señal
disable_overscan=1
max_framebuffer_height=1080
max_framebuffer_width=1920
```

Paquetes:
```bash
sudo apt install -y python3-picamera2 libcamera-apps \
  libgl1-mesa-dri libegl1 libdrm2 avahi-daemon git
sudo usermod -aG video,render "$USER"   # acceso a /dev/dri
```

## Térmica

Disipador **obligatorio**; ventilador recomendado en gabinete cerrado. Sobre 80 °C hay throttling y se ven caídas de frames. La telemetría reporta `vcgencmd measure_temp`.

## Red

`avahi` para `eco-map.local`. Wifi con `wpa_supplicant` o modo AP (ver [[Seguridad-y-Red]]). Ethernet siempre que se pueda: menos variables en una instalación.

## Arranque

Consola sin escritorio, autologin, dos units systemd. Ver [[Despliegue-Raspberry]].

Relacionado: [[Proyector]] · [[Camara]] · [[ADR-005-Motor-Render-OpenGL]]
