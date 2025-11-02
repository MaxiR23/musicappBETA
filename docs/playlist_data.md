-- ============================================
-- CREACIÓN DE TABLAS - Genre Playlists System
-- ============================================

-- Tabla de géneros
CREATE TABLE genres (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL UNIQUE,
  slug text NOT NULL UNIQUE,
  description text,
  sort_order int NOT NULL DEFAULT 0,
  created_at timestamptz DEFAULT now()
);

-- Tabla de playlists curadas
CREATE TABLE genre_playlists (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  genre_id uuid NOT NULL REFERENCES genres(id) ON DELETE CASCADE,
  title text NOT NULL,
  description text,
  thumbnail_url text DEFAULT NULL,
  sort_order int NOT NULL DEFAULT 0,
  track_count int DEFAULT 0,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

-- Tabla de tracks en playlists curadas
CREATE TABLE genre_playlist_tracks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  playlist_id uuid NOT NULL REFERENCES genre_playlists(id) ON DELETE CASCADE,
  track_id uuid NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
  position int NOT NULL,
  added_at timestamptz DEFAULT now(),
  CONSTRAINT unique_playlist_track UNIQUE(playlist_id, track_id),
  CONSTRAINT unique_playlist_position UNIQUE(playlist_id, position)
);

-- Índices
CREATE INDEX idx_genre_playlists_genre_id ON genre_playlists(genre_id);
CREATE INDEX idx_genre_playlists_sort_order ON genre_playlists(sort_order);
CREATE INDEX idx_genre_playlist_tracks_playlist_id ON genre_playlist_tracks(playlist_id);
CREATE INDEX idx_genre_playlist_tracks_track_id ON genre_playlist_tracks(track_id);
CREATE INDEX idx_genre_playlist_tracks_position ON genre_playlist_tracks(playlist_id, position);

-- Trigger para actualizar track_count automáticamente
CREATE OR REPLACE FUNCTION update_genre_playlist_track_count()
RETURNS TRIGGER AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    UPDATE genre_playlists 
    SET track_count = track_count + 1,
        updated_at = now()
    WHERE id = NEW.playlist_id;
  ELSIF TG_OP = 'DELETE' THEN
    UPDATE genre_playlists 
    SET track_count = GREATEST(track_count - 1, 0),
        updated_at = now()
    WHERE id = OLD.playlist_id;
  END IF;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_genre_playlist_track_count
AFTER INSERT OR DELETE ON genre_playlist_tracks
FOR EACH ROW
EXECUTE FUNCTION update_genre_playlist_track_count();

-- Trigger para actualizar updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_genre_playlists_updated_at
BEFORE UPDATE ON genre_playlists
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

ACTUALIZACIÓN PARA DECADAS.

ALTER TABLE genre_playlists 
ADD COLUMN category text DEFAULT NULL;