---
tags: [arquitectura]
---

# Arquitectura general

## Principios estructurales

1. **Dos procesos**: web (FastAPI) y render (ModernGL). Ver [[ADR-006-IPC-Web-Render]].
2. **Todo corre en contenedores**, también en la Raspberry Pi. Ver [[ADR-009-Todo-en-Contenedores]].
3. **SQLite es persistencia, el socket es tiempo real.** El render nunca abre la DB.
4. **Los efectos son archivos**, no código Python ni filas grandes en la DB. Ver [[ADR-011-Archivos-vs-DB]].

## Diagrama de componentes

```mermaid
flowchart TB
    subgraph CLIENT["Navegador — celular o laptop"]
        direction LR
        HTML["Páginas Jinja2<br/>HTMX + Alpine + Pico.css"]
        CANV["Canvas de calibración<br/>handles arrastrables"]
        IMG["Preview de cámara<br/>elemento img"]
        WSC["Cliente WebSocket"]
    end

    subgraph PI["Raspberry Pi — Docker Compose"]
        direction TB

        subgraph CWEB["contenedor ecomap-web"]
            API["FastAPI<br/>routers + Pydantic v2"]
            SVC["services<br/>escenas, calibración, red"]
            REPO["repo SQLite<br/>WAL, threadpool"]
            WSS["WebSocket /ws/telemetry"]
            MJPEG["Proxy MJPEG del preview"]
            NETM["Network manager<br/>escaneo y conexión wifi"]
            BUSC["Bus client"]
        end

        subgraph CREN["contenedor ecomap-render"]
            BUSS["Bus server UDS"]
            SCN["Scene en memoria<br/>inmutable por frame"]
            EFFL["Effect loader<br/>manifiesto + compilación GLSL"]
            GLP["Pipeline ModernGL<br/>FBO por capa → warp → máscara"]
            CAMT["Hilo de visión<br/>OpenCV: motion + calibración"]
            TELE["Telemetría<br/>fps, frame_ms, temp"]
        end

        subgraph VOLS["Volúmenes Docker"]
            direction LR
            VDB[("ecomap-data<br/>ecomap.db")]
            VFX[("ecomap-effects<br/>effect.json + frag.glsl")]
            VMED[("ecomap-media<br/>videos e imágenes")]
            VBUS[("ecomap-bus<br/>bus.sock")]
        end
    end

    subgraph HOST["Host / kernel Linux"]
        DRI["/dev/dri<br/>V3D + KMS/DRM"]
        VID["/dev/video0<br/>V4L2"]
        NMD["NetworkManager<br/>D-Bus del host"]
        AVA["avahi-daemon<br/>mDNS eco-map.local"]
    end

    subgraph EXT["Mundo físico"]
        PROJ["Proyector"]
        WEBCAM["Cámara web USB"]
        SURF["Superficie física"]
        ROUTER["Wifi / router"]
    end

    HTML -->|"HTTP: fragmentos HTML"| API
    CANV -->|"HTTP JSON: PUT points"| API
    WSC <-->|"WebSocket: telemetría y logs"| WSS
    IMG -->|"HTTP: multipart MJPEG"| MJPEG

    API --> SVC
    SVC --> REPO
    SVC --> BUSC
    SVC --> NETM
    WSS --> BUSC

    REPO <-->|"SQL"| VDB
    SVC -->|"lee manifiestos"| VFX

    BUSC <-->|"UDS · JSON Lines"| BUSS
    VBUS -.->|"monta bus.sock"| BUSC
    VBUS -.->|"monta bus.sock"| BUSS

    BUSS --> SCN
    SCN --> GLP
    EFFL -->|"lee GLSL"| VFX
    EFFL --> GLP
    GLP -->|"lee video/imagen"| VMED
    CAMT -->|"textura u_cam, u_motion"| GLP
    GLP --> TELE
    CAMT --> TELE
    TELE --> BUSS

    GLP -->|"EGL + OpenGL ES 3.1"| DRI
    CAMT -->|"captura V4L2"| VID
    NETM -->|"D-Bus"| NMD
    API -.->|"se anuncia"| AVA

    DRI -->|"HDMI"| PROJ
    WEBCAM -->|"USB"| VID
    PROJ -->|"luz"| SURF
    SURF -->|"reflejo"| WEBCAM
    ROUTER <-->|"TCP 8000"| CLIENT
    NMD <--> ROUTER
    AVA <--> ROUTER
```

El **lazo cerrado** es la parte interesante: `GLP → DRI → HDMI → Proyector → Superficie → Cámara → V4L2 → CAMT → GLP`. Eso es la retroalimentación, y también el riesgo de realimentación positiva descrito en [[Modulo-Camara-Feedback]].

## Secuencia — mover un slider (CU-04)

```mermaid
sequenceDiagram
    autonumber
    participant U as Usuario
    participant B as Navegador (Alpine)
    participant W as ecomap-web
    participant D as SQLite
    participant R as ecomap-render
    participant P as Proyector

    U->>B: arrastra slider "speed"
    B->>B: throttle 50 ms
    B->>W: PUT /api/layers/12/params {speed: 0.7}
    W->>W: valida con Pydantic contra el manifiesto
    W->>R: UDS {"op":"param","layer":12,"key":"speed","value":0.7}
    R->>R: aplica uniform entre frames
    R->>P: siguiente frame ya con el valor nuevo
    W-->>B: 200 + fragmento HTML del control
    Note over W,D: en paralelo, debounce 500 ms
    W->>D: UPDATE layer SET params = ...
    R-->>W: {"ev":"tele","fps":59.4}
    W-->>B: WebSocket: telemetría
```

Latencia percibida = throttle + HTTP local + un frame ≈ **60–80 ms**, dentro de RNF-2. La escritura a disco queda fuera del camino crítico: protege la SD y no agrega latencia. Ver [[ADR-004-SQLite]].

## Secuencia — auto-calibración con cámara (CU-03)

```mermaid
sequenceDiagram
    autonumber
    participant B as Navegador
    participant W as ecomap-web
    participant R as ecomap-render
    participant C as Hilo de visión
    participant P as Proyector

    B->>W: POST /api/calibration/auto {method:"graycode"}
    W-->>B: 202 {task_id}
    W->>R: {"op":"calibrate","method":"graycode"}
    R->>C: fija exposición y balance manuales
    loop 22 patrones: h + v, normal + inverso
        R->>P: proyecta patrón n
        R->>C: espera 2 frames de asentamiento
        C->>C: captura y almacena
        C-->>W: {"ev":"calib","progress":0.45,"stage":"graycode_v"}
        W-->>B: WebSocket: progreso
    end
    C->>C: decodifica Gray code → correspondencias
    C->>C: cv2.findHomography con RANSAC → H, rms
    C-->>R: H lista
    R-->>W: {"ev":"calib","done":true,"rms":2.1}
    W->>W: guarda en tabla calibration
    W-->>B: WebSocket: terminado, rms 2.1 px
```

Si `rms` supera el umbral, la UI lo reporta y ofrece calibración manual. Ver [[Modulo-Calibracion]].

## Reparto de responsabilidades

| | ecomap-web | ecomap-render |
|---|---|---|
| Dueño de | SQLite, HTTP, WebSocket, red | contexto GL, HDMI, cámara |
| Ritmo | por petición | 60 fps |
| Si se cae | la proyección **sigue** | la UI muestra "render offline" |
| Reinicio | instantáneo, sin cortar la luz | ~2 s de negro |

Relacionado: [[Modulo-Web-API]] · [[Modulo-Render]] · [[Modulo-Red]] · [[Estructura-Repositorio]] · [[Presupuesto-de-Rendimiento]] · [[Eco-Map]]
