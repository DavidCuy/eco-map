---
tags: [hardware, minipc, setup]
---

# Mini PC x86 — configuración

Plataforma de **referencia** del proyecto. Ver [[ADR-013-Plataforma-Agnostica]].

## El equipo disponible

KAMRUI GK3PLUS: **Intel Celeron N3350**, 8 GB RAM, SSD 256 GB, 2×HDMI + VGA, WiFi y BT.

| Dato | Valor | Qué implica |
|---|---|---|
| CPU | 2 núcleos / 2 hilos, 1.1–2.4 GHz, Goldmont 2016, 6 W | **Es el cuello.** Menos núcleos que una Pi 4 |
| GPU | Intel HD Graphics 500, 12 EUs, hasta 650 MHz | Más margen que el VideoCore VI de la Pi 4 |
| Video | HDMI 1.4b | 1080p60 sí; 4K solo a 30 Hz, irrelevante para v1 |
| RAM | 8 GB | De sobra: el sistema entero usa cientos de MB |
| Disco | SSD | Sin el problema de desgaste de la SD |
| Salidas | 2×HDMI | Habilita multi-proyector en v2. VGA es analógico, ignorarlo |

> [!warning] Verificar el CPU al primer arranque
> El GK3PLUS se vende con N3350, N95, N97 y N100 según variante, y el anuncio tenía dos ASIN distintos. Con un N100 la historia mejora bastante: 4 núcleos y UHD Gen12 con 24 EUs.
> ```bash
> lscpu | head -20
> sudo lshw -C display
> ```
> Con el dato real hay que recalcular [[Presupuesto-de-Rendimiento]].

## Sistema

**Debian 13 o Ubuntu Server, sin entorno gráfico.** El requisito no es estético: si hay un escritorio corriendo, él toma el *DRM master* y el contenedor de render no puede sacar video por KMS.

```bash
sudo apt install -y avahi-daemon network-manager podman
sudo usermod -aG video,render "$USER"   # acceso a /dev/dri
sudo hostnamectl set-hostname eco-map
```

El driver `i915` viene en el kernel; no hace falta instalar nada equivalente al `vc4-kms-v3d` de la Pi. Para confirmar que la GPU está disponible:

```bash
ls -l /dev/dri/            # debe existir card0 y renderD128
sudo apt install -y mesa-utils && glxinfo -B | grep -E 'OpenGL (renderer|version)'
```

## Rootless o root

Rootless alcanza, con dos condiciones:

1. El usuario del servicio pertenece a `video` y `render`, **y volvió a iniciar sesión** después
   del `usermod`: `keep-groups` pasa los grupos que el proceso ya tiene, no los busca de nuevo.
2. El compose usa `group_add: [keep-groups]`, no la lista de grupos. Ver
   [[ADR-012-Podman-Desarrollo-Local]].

```bash
id                          # deben aparecer video y render
ls -l /dev/dri/card0        # en Debian: root:video 0660
podman info --format '{{.Host.Security.Rootless}} {{.Host.OCIRuntime.Name}}'   # true crun
```

El otro requisito es que **nada más tenga el DRM master**: sin servidor X ni Wayland corriendo, el
contenedor lo toma sin privilegios. Por eso el host va sin entorno gráfico.

Lo que sí puede necesitar root más adelante es la configuración de wifi del Hito 3: polkit deniega
por defecto que un usuario sin privilegios controle NetworkManager.

## Diferencias frente a la Raspberry Pi

| | Mini PC | Raspberry Pi |
|---|---|---|
| Driver Mesa | `i915` (crocus/iris) | `v3d` |
| Config de arranque | nada especial | `dtoverlay=vc4-kms-v3d` en `config.txt` |
| Arquitectura | amd64 (igual que la laptop) | arm64 |
| Compose | `compose.minipc.yml` | `compose.pi.yml` |
| Consumo | ~10–15 W | ~5–7 W |
| Núcleos | 2 | 4 |

La consecuencia práctica más útil: **la imagen de la mini PC es la misma arquitectura que la de desarrollo**, así que lo que se valida en la laptop aplica sin recompilar.

## Puesta en marcha

```bash
git clone <repo> /opt/ecomap && cd /opt/ecomap
podman build --target runtime -t ecomap:latest .
podman-compose -f compose.minipc.yml up -d
```

Arranque automático y respaldos: [[Despliegue-Raspberry]] sirve igual, cambiando el archivo compose. La unit de systemd está en `scripts/ecomap.service`.

## Qué hay que medir cuando esté montada

Esto es lo que falta para cerrar el presupuesto de rendimiento con números reales en vez de estimaciones:

- [ ] `frame_ms` de cada efecto a 1080p en modo `kms`, no en `headless`.
- [ ] Carga de CPU con el hilo de cámara activo: es la prueba de fuego de los 2 núcleos.
- [ ] Temperatura sostenida tras 30 min proyectando (el GK3PLUS tiene ventilador).
- [ ] Tiempo de encendido hasta proyección (RNF-3: menos de 20 s).

Relacionado: [[ADR-013-Plataforma-Agnostica]] · [[Raspberry-Pi-Setup]] · [[Proyector]] · [[Camara]] · [[Presupuesto-de-Rendimiento]]
