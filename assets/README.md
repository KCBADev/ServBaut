# assets

Imágenes que la aplicación carga en tiempo de ejecución.

## `ctm-logo.png`

El monograma «CTM» que aparece en la barra lateral.

Sale del logo original del taller, `Plantillas/Work_order/assets/ctm-logo-mark.png`,
con dos cambios:

1. **Recortado al ícono.** El original trae debajo el texto «CHECA TU MOTOR».
   Las dos partes están separadas por una franja de píxeles transparentes
   (filas 391 a 420), que es por donde se corta.
2. **Revisado al gris claro del tema** (`#D2D8DE`, el mismo `styles.TEXTO`),
   conservando el canal alfa. El original es tinta casi negra: sobre la barra
   lateral oscura sería invisible.

### Para regenerarlo

El original **no se versiona** — `Plantillas/*/assets/` está en el
`.gitignore`, porque son 900 KB de material del lienzo de diseño que la app
no necesita. Si hace falta rehacerlo y tienes el archivo original a mano:

```python
from PIL import Image
import numpy as np

TINTA = (210, 216, 222)  # styles.TEXTO

a = np.array(Image.open("ctm-logo-mark.png").convert("RGBA"))
mono = a[:391, :, :]                       # fuera el texto de abajo

cols = np.where(mono[:, :, 3].max(axis=0) > 0)[0]
filas = np.where(mono[:, :, 3].max(axis=1) > 0)[0]
mono = mono[filas.min():filas.max() + 1, cols.min():cols.max() + 1, :]

mono[:, :, 0], mono[:, :, 1], mono[:, :, 2] = TINTA
Image.fromarray(mono, "RGBA").save("assets/ctm-logo.png", optimize=True)
```

Si cambia el color del texto en `styles.py`, hay que volver a generarlo con
el valor nuevo: el color va horneado en el PNG, no se aplica por CSS.
