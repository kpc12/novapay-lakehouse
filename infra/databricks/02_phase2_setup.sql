-- Phase 2: managed volume for Auto Loader checkpoints and schema tracking.
CREATE VOLUME IF NOT EXISTS novapay_dev.ops.checkpoints
  COMMENT 'Auto Loader checkpoints and schema locations (one folder per stream)';
