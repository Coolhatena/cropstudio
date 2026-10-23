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
5. **Exportar todos** permite seleccionar proyecto completo o imagen actual, formato y calidad.
   Después elige una **carpeta contenedora**: dentro se creará `<nombre_del_proyecto>_recortes`,
   conservando las subcarpetas de cada imagen. La exportación muestra el destino, el progreso y
   permite cancelar; los archivos terminados se conservan.

Por ejemplo, si abres `SELECCIONES DEPORTIVAS` y eliges `D:\Exportaciones` como carpeta contenedora:

```text
Origen:
SELECCIONES DEPORTIVAS/CAMPUS MEXICALI/NATACIÓN/EQUIPO/foto.jpg

Recorte JPG exportado:
D:/Exportaciones/SELECCIONES DEPORTIVAS_recortes/CAMPUS MEXICALI/NATACIÓN/EQUIPO/foto_crop_01.jpg
```

Se crean únicamente las subcarpetas necesarias al escribir recortes válidos, sin copiar carpetas
vacías, originales ni otros archivos. Las imágenes de la raíz se exportan directamente dentro
de `<nombre_del_proyecto>_recortes`. Al exportar solo la imagen actual también se conserva toda
su ruta relativa. Si la carpeta de salida ya existe, se reutiliza; los nombres repetidos reciben
sufijos dentro de cada subcarpeta, sin sobrescribir archivos de exportaciones anteriores.

Para repetir un encuadre, selecciona un recorte y pulsa **Guardar recorte como plantilla**.
El formulario copia su nombre, X, Y, ancho y alto del recorte, y dimensiones de salida. Puedes
editarlo antes de guardar. El recorte original se conserva y la nueva plantilla queda seleccionada.
En otra imagen, pulsa **Nuevo recorte desde plantilla** para repetir el rectángulo exactamente,
sin escalarlo ni centrarlo de nuevo, aunque la imagen tenga otras dimensiones.

Las plantillas nuevas tienen activada **Guardar posición y tamaño**. Sus coordenadas son absolutas
y conservan su precisión decimal al copiar un recorte; el ancho y alto del recorte son independientes
de la resolución de salida, pero deben tener la misma proporción. Si no coinciden, corrige el
recorte antes de guardarlo como plantilla. Si el rectángulo no cabe en la imagen de destino, aparece
**“La plantilla es demasiado grande para la imagen actual”** y no se crea ningún recorte.

Las plantillas anteriores y las cuatro iniciales mantienen **Centrado automático**. Puedes asignarles
una geometría desde **Gestionar plantillas → Editar**, activando **Guardar posición y tamaño**.
Al desactivar esta opción se recupera el centrado automático. El selector y el gestor indican el modo
de cada plantilla. Las plantillas siguen siendo globales y se aplican sobre la imagen actual.

Cada recorte conserva su resolución y proporción aunque cambies o borres la plantilla original.
También conserva su posición y tamaño aunque se edite la geometría de su plantilla.
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
El esquema SQLite se actualiza automáticamente de versión 1 a 2 mediante una transacción, conservando
los datos y la plantilla predeterminada. Usa la versión actualizada del programa para abrir esa base.
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

Validación local completada en Windows 11 con Python 3.14.7: **121 pruebas aprobadas**, empaquetado
con PyInstaller y arranque/cierre del ejecutable con la plataforma nativa de Windows (código 0,
cuatro plantillas disponibles). La interacción se comprobó con pruebas Qt automatizadas y una
captura del editor; no se realizó una sesión manual prolongada ni se probó en otros equipos.
La suite incluye migración y rollback del esquema, geometría fija con precisión decimal, creación
desde un recorte, repetición en distintas imágenes, avisos de límites y exportación JPG/PNG/WEBP/SVG.
También verifica la jerarquía de carpetas con nombres Unicode, exportación de una sola imagen,
reutilización del destino, límites de rutas, errores por rama y cancelación sin crear ramas pendientes.
