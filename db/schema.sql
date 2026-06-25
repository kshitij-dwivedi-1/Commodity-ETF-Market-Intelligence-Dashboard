-- Commodity & ETF Market Intelligence Dashboard schema
-- Suggested MySQL settings for dashboard workloads:
-- innodb_buffer_pool_size = 512M
-- query_cache_size = 64M
-- Use covering indexes for all dashboard queries

CREATE DATABASE IF NOT EXISTS market_intelligence;
USE market_intelligence;

CREATE TABLE IF NOT EXISTS symbols (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  symbol        VARCHAR(20)  NOT NULL UNIQUE,
  name          VARCHAR(100) NOT NULL,
  type          ENUM('commodity','etf') NOT NULL,
  unit          VARCHAR(30),
  currency      VARCHAR(10)  DEFAULT 'USD',
  api_source    VARCHAR(50),
  is_active     TINYINT(1)   DEFAULT 1,
  created_at    DATETIME     DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS price_history (
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  symbol_id     INT          NOT NULL,
  ts            DATETIME     NOT NULL,
  open          DECIMAL(18,6),
  high          DECIMAL(18,6),
  low           DECIMAL(18,6),
  close         DECIMAL(18,6) NOT NULL,
  volume        BIGINT,
  source        VARCHAR(50),
  is_anomaly    TINYINT(1)   DEFAULT 0,
  ingested_at   DATETIME     DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (symbol_id) REFERENCES symbols(id),
  UNIQUE KEY uq_symbol_ts (symbol_id, ts),
  INDEX idx_symbol_ts     (symbol_id, ts DESC),
  INDEX idx_ts            (ts DESC),
  INDEX idx_anomaly       (is_anomaly, ts DESC)
) ROW_FORMAT=COMPRESSED;

CREATE TABLE IF NOT EXISTS correlation_matrix (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  symbol_a_id   INT     NOT NULL,
  symbol_b_id   INT     NOT NULL,
  window_days   INT     NOT NULL,
  correlation   DECIMAL(8,6),
  computed_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_corr_symbols_window (symbol_a_id, symbol_b_id, window_days),
  INDEX idx_computed (computed_at DESC),
  INDEX idx_symbols  (symbol_a_id, symbol_b_id, window_days),
  FOREIGN KEY (symbol_a_id) REFERENCES symbols(id),
  FOREIGN KEY (symbol_b_id) REFERENCES symbols(id)
);

CREATE TABLE IF NOT EXISTS anomaly_events (
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  symbol_id     INT     NOT NULL,
  ts            DATETIME NOT NULL,
  price         DECIMAL(18,6),
  z_score       DECIMAL(8,4),
  method        VARCHAR(20),
  flagged_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_symbol_ts (symbol_id, ts DESC),
  FOREIGN KEY (symbol_id) REFERENCES symbols(id)
);

CREATE TABLE IF NOT EXISTS price_forecasts (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  symbol_id     INT     NOT NULL,
  forecast_ts   DATETIME NOT NULL,
  predicted     DECIMAL(18,6),
  lower_bound   DECIMAL(18,6),
  upper_bound   DECIMAL(18,6),
  model         VARCHAR(30),
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_symbol_forecast_model (symbol_id, forecast_ts, model),
  INDEX idx_symbol_forecast (symbol_id, forecast_ts),
  FOREIGN KEY (symbol_id) REFERENCES symbols(id)
);

CREATE TABLE IF NOT EXISTS etl_runs (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  run_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
  duration_sec  DECIMAL(8,3),
  rows_inserted INT,
  rows_updated  INT,
  errors        TEXT,
  status        ENUM('success','partial','failed')
);
