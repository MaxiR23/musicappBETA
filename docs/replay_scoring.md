# Replay Scoring: Exponential Decay

## Problema

La función `get_replay_songs` ordenaba los resultados por `play_count DESC`.
Esto causaba que canciones con muchas reproducciones acumuladas hace semanas
se mantuvieran en el tope, incluso si el usuario ya no las escuchaba.

## Solucion

Se reemplazó el `ORDER BY play_count DESC` por un score con decaimiento
exponencial. Cada reproducción se pondera según qué tan reciente fue:

```
score = SUM( e^( -tiempo_desde_play / (86400 * half_life) ) )
```

- Un play de hoy vale ~1.0
- Un play de hace 20 dias vale ~0.37
- Un play de hace 40 dias vale ~0.14
- Un play de hace 60 dias vale ~0.05

## Half-life

El valor actual es **20 dias**. Esto significa que a los 20 dias, una
reproducción vale aproximadamente la mitad de su peso original.

Ajustar si es necesario:

- Mas bajo (ej: 14) = ranking cambia mas rapido, favorece lo muy reciente.
- Mas alto (ej: 30) = ranking mas estable, las canciones tardan mas en caer.

El valor se encuentra en la linea `ORDER BY` de la funcion:

```sql
ORDER BY SUM(EXP(-EXTRACT(EPOCH FROM (NOW() - pe.played_at)) / (86400 * 20))) DESC
--                                                                        ^^
--                                                              half_life en dias
```

## Comportamiento por tipo de usuario

**Usuario activo**: plays recientes suben rapido, obsesiones viejas bajan
gradualmente. El ranking refleja lo que esta escuchando ahora.

**Usuario inactivo**: todos los scores decaen al mismo ritmo, el ranking
relativo se mantiene. Sigue mostrando sus canciones mas escuchadas sin
quedar vacío.

**Usuario que vuelve**: cualquier play nuevo tiene score alto respecto a los
antiguos que ya decayeron, asi que sube rapido al tope.

## Impacto en performance

Ninguno. `EXP()` es una operacion matematica por fila, costo despreciable.
La query sigue usando el indice `pe_user_time_idx (user_id, played_at DESC)`
para filtrar. Escala igual con cualquier cantidad de usuarios.

## Cambio aplicado

Solo se modifico el `ORDER BY` de la funcion `get_replay_songs` en Supabase.
No se requirieron cambios en el backend (Python) ni en el frontend (React Native).

### Antes

```sql
ORDER BY play_count DESC
```

### Despues

```sql
ORDER BY SUM(EXP(-EXTRACT(EPOCH FROM (NOW() - pe.played_at)) / (86400 * 20))) DESC
```