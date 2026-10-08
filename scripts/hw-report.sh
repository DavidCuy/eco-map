#!/usr/bin/env bash
# Inventario del host para cerrar el bloque "Al recibir la mini PC" del issue #33.
# Se corre EN el equipo destino (mini PC o Pi), no en la laptop, y su salida es
# markdown pegable como comentario del issue:
#
#   ssh eco-map 'sudo bash -s' < scripts/hw-report.sh > hw-report.md
#
# Sin sudo igual corre, pero `lshw` y la lista de modos DRM salen incompletas.
# No instala nada: lo que falta se reporta como faltante, porque "qué
# herramientas no están" también es un dato del host.
set -uo pipefail

have() { command -v "$1" >/dev/null 2>&1; }

# Un bloque por comando. Si el comando no existe se dice, en vez de dejar un
# fenced block vacío que no distingue "no instalado" de "sin salida".
blk() {
  local titulo="$1"; shift
  echo "**$titulo**"
  echo
  echo '```'
  if have "${1}"; then
    "$@" 2>&1 || echo "(comando falló con código $?)"
  else
    echo "(no instalado: $1)"
  fi
  echo '```'
  echo
}

# Para pipelines y globs, que `blk` no puede ejecutar como argv.
blk_sh() {
  local titulo="$1" cmd="$2"
  echo "**$titulo**"
  echo
  echo '```'
  eval "$cmd" 2>&1 || echo "(falló con código $?)"
  echo '```'
  echo
}

echo "# Reporte de hardware — $(hostname) — $(date -Iseconds)"
echo
if [ "$(id -u)" -ne 0 ]; then
  echo "> Corrido **sin root**: \`lshw\` y algunos sysfs van a salir parciales."
  echo
fi

echo "## Identidad y sistema"
echo
blk_sh "Sistema" "cat /etc/os-release | grep -E '^(PRETTY_NAME|VERSION_ID)='"
blk "Kernel" uname -a
blk_sh "Arquitectura" "dpkg --print-architecture 2>/dev/null || uname -m"
blk "Tiempo de arranque (RNF-3: < 20 s hasta proyección)" systemd-analyze
blk_sh "Usuario y grupos (se esperan video y render)" "id"

echo "## CPU"
echo
echo "El GK3PLUS se vende con N3350, N95, N97 y N100. Este dato decide la columna"
echo "mini PC de \`Presupuesto-de-Rendimiento\`: núcleos y EUs cambian el reparto."
echo
blk_sh "Modelo y núcleos" "lscpu | head -20"
blk_sh "Escalado de frecuencia" "cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || echo '(sin cpufreq expuesto)'"
blk_sh "RAM" "free -h"
blk_sh "Disco" "df -h / | tail -1"

echo "## GPU y DRM"
echo
blk "Display" lshw -C display
blk_sh "Driver en kernel (se espera i915 en x86, v3d en Pi)" "lsmod | grep -E '^(i915|v3d|vc4)' || echo '(ningún módulo i915/v3d/vc4 cargado)'"
blk_sh "Nodos DRM (se esperan card0 y renderD128)" "ls -l /dev/dri/ 2>&1"
blk "OpenGL por GLX" glxinfo -B
blk "EGL (es el backend real en kms)" eglinfo -B

echo "### Quién tiene el DRM master"
echo
echo "El contenedor de render solo puede sacar video si **nada más** tomó el DRM"
echo "master. Un escritorio corriendo lo bloquea; eso es el requisito de host"
echo "sin entorno gráfico, no una preferencia."
echo
blk_sh "Target por defecto (se espera multi-user.target)" "systemctl get-default"
blk_sh "Servidores gráficos corriendo (se espera vacío)" "pgrep -a -f 'Xorg|wayland|gdm|sddm|lightdm|gnome-shell|weston' || echo '(ninguno: DRM master libre)'"
blk_sh "Sesiones con asiento gráfico" "loginctl list-sessions --no-legend 2>/dev/null || echo '(sin sesiones)'"

echo "### Salidas de video"
echo
echo "Los modos listados vienen del EDID del proyector: confirman si acepta"
echo "1920x1080@60 antes de depurar el render."
echo
blk_sh "Conectores y estado" "for c in /sys/class/drm/card*-*; do [ -e \"\$c/status\" ] && echo \"\$(basename \"\$c\"): \$(cat \"\$c/status\")\"; done 2>&1"
blk_sh "Modos del primer conector conectado" "for c in /sys/class/drm/card*-*; do if [ -e \"\$c/status\" ] && [ \"\$(cat \"\$c/status\")\" = connected ]; then echo \"== \$(basename \"\$c\")\"; head -8 \"\$c/modes\"; fi; done 2>&1"

echo "## Cámara USB"
echo
echo "MJPG no es opcional: en YUYV el ancho de banda USB 2.0 limita 640x480 a"
echo "pocos fps (ADR-010). Y los controles de exposición tienen que **respetarse**,"
echo "no solo aparecer: si la cámara los ignora, el Gray code del Hito 5 no"
echo "decodifica porque el brillo cambia entre capturas y sus inversos."
echo
blk_sh "Dispositivos" "ls -l /dev/video* 2>/dev/null || echo '(sin /dev/video*: cámara no conectada)'"
blk_sh "Rutas estables (es lo que va en el compose, no /dev/videoN)" "ls -l /dev/v4l/by-id/ 2>/dev/null || echo '(sin /dev/v4l/by-id)'"
blk "Dispositivos v4l2" v4l2-ctl --list-devices
blk "Formatos y fps" v4l2-ctl --list-formats-ext
blk "Controles (buscar exposure_auto y white_balance)" v4l2-ctl --list-ctrls

echo "## Contenedores"
echo
blk_sh "Podman" "podman --version 2>&1"
blk_sh "Rootless y runtime (se espera: false crun)" "podman info --format '{{.Host.Security.Rootless}} {{.Host.OCIRuntime.Name}}' 2>&1"
blk_sh "podman-compose" "podman-compose --version 2>&1 | head -3"

echo "## Red (Hito 3)"
echo
blk_sh "Hostname (se espera eco-map)" "hostnamectl --static 2>/dev/null || hostname"
blk_sh "avahi y NetworkManager activos" "systemctl is-active avahi-daemon network-manager NetworkManager 2>&1 | paste -sd' '"
blk_sh "Direcciones" "ip -brief -4 addr show scope global"
blk_sh "Resolución de .local desde el propio host" "getent hosts \"\$(hostname).local\" || echo '(no resuelve: probar también desde otra máquina de la red)'"

echo "---"
echo
echo "Generado por \`scripts/hw-report.sh\`. Pegar como comentario en el issue #33"
echo "y recalcular \`Presupuesto-de-Rendimiento\` con el CPU y la GPU reales."
