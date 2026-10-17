-- Preserve historical revision bytes/hashes; empty arrays mean unclassified.
ALTER TABLE model_revisions ADD COLUMN model_types text[] NOT NULL DEFAULT '{}';
ALTER TABLE model_revisions ADD COLUMN input_modalities text[] NOT NULL DEFAULT '{}';
ALTER TABLE model_revisions ADD COLUMN output_modalities text[] NOT NULL DEFAULT '{}';
ALTER TABLE model_revisions ADD CONSTRAINT model_type_values CHECK
    (model_types <@ ARRAY['text','tts','multimodal','vision','speech_recognition','decision','embedding','image_generation','video_generation']::text[]);
ALTER TABLE model_revisions ADD CONSTRAINT model_input_values CHECK
    (input_modalities <@ ARRAY['text','audio','image','video','vector']::text[]);
ALTER TABLE model_revisions ADD CONSTRAINT model_output_values CHECK
    (output_modalities <@ ARRAY['text','audio','image','video','vector']::text[]);
