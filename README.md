# Crop Studio

Editor de escritorio para Windows con PySide6. Los originales permanecen intactos: los proyectos,
plantillas globales y recortes se guardan en `%LOCALAPPDATA%\CropStudio\cropstudio.sqlite3`.

## Instalar y ejecutar

Requiere Windows y Python 3.13 o posterior. Instala [uv](https://docs.astral.sh/uv/getting-started/installation/)
y ejecuta desde esta carpeta:

```powershell
uv sync
uv run cropstudio
# Alternativa:
uv run python main.py
```

## Uso

1. Selecciona una carpeta. Se incluyen imágenes JPG/JPEG, PNG y WEBP de sus subcarpetas.
2. Elige una plantilla a la derecha y pulsa **Nuevo recorte desde plantilla** tantas veces como necesites.
   Las cuatro plantillas iniciales son editables en **Gestionar plantillas**; allí puedes crear,
   duplicar, eliminar y marcar la predeterminada. Son comunes a todos los proyectos.
3. Mueve el recorte o arrastra sus ocho controles. Para recortes superpuestos puedes usar la lista
   derecha. Los campos numéricos se aplican con Enter o al salir del campo. **Dibujar recorte**
   permite crear rectángulos libres. La rueda amplía; botón central o Ctrl+arrastrar desplaza.
4. Los cambios se guardan al terminar cada edición. Al volver a seleccionar la carpeta se restaura
   el proyecto. **Actualizar carpeta** detecta archivos nuevos y ausentes sin borrar sus recortes.
5. **Exportar todos** permite seleccionar proyecto completo o imagen actual, formato, calidad y destino.
   La exportación muestra progreso y permite cancelar; los archivos terminados se conservan.

Cada recorte conserva su resolución y proporción aunque cambies o borres la plantilla original.
Las imágenes pequeñas se amplían a la resolución pedida. Si geometría y salida no coinciden,
**Ajustar a resolución de salida** corrige el rectángulo explícitamente. Los recortes incompatibles
se omiten con un error durante la exportación. Los nombres repetidos reciben sufijos sin sobrescribir.
Las transparencias se componen sobre blanco para JPG.

Formatos de exportación: JPG, PNG, WEBP y SVG. Cada SVG es un archivo autónomo con el recorte
PNG incrustado, dimensiones en píxeles y `viewBox` coincidentes con la resolución de salida.
Conserva la transparencia y no necesita el original para abrirse. El contenido sigue siendo una
imagen de píxeles; no se convierte en trazados vectoriales. La calidad solo se aplica a JPG y WEBP.

## Datos y recuperación

La geometría usa píxeles de la imagen original después de aplicar EXIF, origen superior izquierdo,
coordenadas decimales y extremos derecho/inferior exclusivos. La resolución de salida es independiente.
No cambies externamente las dimensiones de una imagen después de definir sus recortes: si dejan de
ser válidos, debes ajustarlos antes de exportar.

Ante un fallo al guardar, los cambios permanecen en memoria y aparece **Reintentar guardado**.
La aplicación impide cambiar de imagen/proyecto o cerrar hasta guardarlos. Una caída del proceso
durante ese fallo puede perder únicamente los cambios aún pendientes. Copia el archivo SQLite con
la aplicación cerrada para respaldar proyectos y plantillas.

## Pruebas y ejecutable

```powershell
uv run pytest -q
uv run pyinstaller --noconfirm CropStudio.spec
.\dist\CropStudio\CropStudio.exe
# Comprobación de arranque sin abrir una ventana interactiva:
.\dist\CropStudio\CropStudio.exe --smoke-test .\build\smoke-result.json
```

Distribuye la carpeta completa `dist\CropStudio`, no solo el `.exe`. El ejecutable es local y no
está firmado digitalmente. Las pruebas Qt usan la plataforma `offscreen` y bases SQLite temporales;
incluyen un flujo con 100 imágenes, reinicio, exportación y comparación de originales.

Validación local completada en Windows 11 con Python 3.14.7: **67 pruebas aprobadas**, empaquetado
con PyInstaller y arranque/cierre del ejecutable con la plataforma nativa de Windows (código 0,
cuatro plantillas disponibles). La interacción se comprobó con pruebas Qt automatizadas y una
captura del editor; no se realizó una sesión manual prolongada ni se probó en otros equipos.
