-- MIRI ERD v2 DDL (postgres) — app/models.py 에서 자동 생성. 직접 고치지 말고 모델을 고친 뒤 다시 생성하세요.

CREATE TABLE business_categories (
	category_id BIGSERIAL NOT NULL, 
	category_code VARCHAR(30) NOT NULL, 
	category_name VARCHAR(100) NOT NULL, 
	parent_category VARCHAR(100) NOT NULL, 
	has_sales_data BOOLEAN NOT NULL, 
	display_group VARCHAR(50), 
	PRIMARY KEY (category_id)
);

CREATE UNIQUE INDEX ix_business_categories_category_code ON business_categories (category_code);

CREATE TABLE category_cost_profiles (
	parent_category VARCHAR(100) NOT NULL, 
	default_cogs_rate FLOAT, 
	source TEXT, 
	PRIMARY KEY (parent_category)
);

CREATE TABLE commercial_areas (
	area_id BIGSERIAL NOT NULL, 
	area_code VARCHAR(20) NOT NULL, 
	area_name VARCHAR(100) NOT NULL, 
	area_level VARCHAR(20) NOT NULL, 
	parent_area_id BIGINT, 
	province VARCHAR(50) NOT NULL, 
	city VARCHAR(50), 
	district VARCHAR(50), 
	latitude FLOAT, 
	longitude FLOAT, 
	radius_meter INTEGER, 
	boundary_geojson TEXT, 
	PRIMARY KEY (area_id), 
	FOREIGN KEY(parent_area_id) REFERENCES commercial_areas (area_id)
);

CREATE UNIQUE INDEX ix_commercial_areas_area_code ON commercial_areas (area_code);

CREATE TABLE data_sources (
	source_id BIGSERIAL NOT NULL, 
	source_name VARCHAR(100) NOT NULL, 
	source_type VARCHAR(50) NOT NULL, 
	update_cycle VARCHAR(50) NOT NULL, 
	description TEXT, 
	dataset_code VARCHAR(30), 
	url VARCHAR(255), 
	file_name VARCHAR(100), 
	PRIMARY KEY (source_id), 
	UNIQUE (source_name)
);

CREATE TABLE policy_supports (
	policy_id BIGSERIAL NOT NULL, 
	policy_name VARCHAR(150) NOT NULL, 
	provider VARCHAR(100), 
	target_region VARCHAR(100) NOT NULL, 
	target_category VARCHAR(100) NOT NULL, 
	target_user VARCHAR(50) NOT NULL, 
	support_type VARCHAR(50) NOT NULL, 
	summary TEXT, 
	apply_url VARCHAR(255), 
	start_date DATE, 
	end_date DATE, 
	checked_at DATE, 
	PRIMARY KEY (policy_id)
);

CREATE TABLE scoring_model_versions (
	model_version VARCHAR(30) NOT NULL, 
	model_type VARCHAR(30) NOT NULL, 
	params_json TEXT NOT NULL, 
	train_quarters_json TEXT NOT NULL, 
	metrics_json TEXT, 
	trained_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	PRIMARY KEY (model_version)
);

CREATE TABLE users (
	user_id BIGSERIAL NOT NULL, 
	email VARCHAR(100) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	name VARCHAR(50) NOT NULL, 
	role VARCHAR(30) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (user_id)
);

CREATE UNIQUE INDEX ix_users_email ON users (email);

CREATE TABLE analysis_requests (
	request_id BIGSERIAL NOT NULL, 
	public_id VARCHAR(36) NOT NULL, 
	user_id BIGINT, 
	claim_token_hash VARCHAR(64), 
	main_area_id BIGINT NOT NULL, 
	budget BIGINT NOT NULL, 
	monthly_rent_limit BIGINT NOT NULL, 
	labor_cost BIGINT NOT NULL, 
	initial_investment BIGINT NOT NULL, 
	business_goal VARCHAR(100) NOT NULL, 
	user_type VARCHAR(30) NOT NULL, 
	other_fixed BIGINT NOT NULL, 
	loan_amount BIGINT NOT NULL, 
	loan_rate_annual FLOAT NOT NULL, 
	owner_salary BIGINT NOT NULL, 
	licenses_json TEXT NOT NULL, 
	categories_json TEXT NOT NULL, 
	cogs_json TEXT, 
	excluded_json TEXT, 
	place_name VARCHAR(100), 
	center_lat FLOAT, 
	center_lng FLOAT, 
	radius_meter INTEGER, 
	data_quarter INTEGER NOT NULL, 
	model_version VARCHAR(30) NOT NULL, 
	notices_json TEXT NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (request_id), 
	FOREIGN KEY(user_id) REFERENCES users (user_id) ON DELETE CASCADE, 
	FOREIGN KEY(main_area_id) REFERENCES commercial_areas (area_id)
);

CREATE UNIQUE INDEX ix_analysis_requests_public_id ON analysis_requests (public_id);

CREATE INDEX ix_analysis_requests_user_id ON analysis_requests (user_id);

CREATE TABLE area_category_features (
	feature_id BIGSERIAL NOT NULL, 
	area_id BIGINT NOT NULL, 
	category_id BIGINT NOT NULL, 
	base_quarter INTEGER NOT NULL, 
	model_version VARCHAR(30) NOT NULL, 
	exposure_4q FLOAT NOT NULL, 
	closures_4q FLOAT NOT NULL, 
	openings_4q FLOAT NOT NULL, 
	stores_avg_4q FLOAT NOT NULL, 
	rate_eb FLOAT, 
	local_weight FLOAT, 
	sales_ps_m FLOAT, 
	avg_ticket FLOAT, 
	tx_ps_day FLOAT, 
	demand_score FLOAT, 
	pred_q_rate FLOAT NOT NULL, 
	pred_annual_rate FLOAT NOT NULL, 
	risk_score INTEGER NOT NULL, 
	risk_level VARCHAR(10) NOT NULL, 
	location_risk_pct INTEGER NOT NULL, 
	confidence VARCHAR(10) NOT NULL, 
	payload_json TEXT NOT NULL, 
	PRIMARY KEY (feature_id), 
	UNIQUE (area_id, category_id, base_quarter, model_version), 
	FOREIGN KEY(area_id) REFERENCES commercial_areas (area_id), 
	FOREIGN KEY(category_id) REFERENCES business_categories (category_id), 
	FOREIGN KEY(model_version) REFERENCES scoring_model_versions (model_version)
);

CREATE INDEX ix_area_category_features_area_id ON area_category_features (area_id);

CREATE INDEX ix_acf_q_model ON area_category_features (base_quarter, model_version);

CREATE INDEX ix_area_category_features_category_id ON area_category_features (category_id);

CREATE TABLE area_metrics (
	metric_id BIGSERIAL NOT NULL, 
	area_id BIGINT NOT NULL, 
	metric_date DATE NOT NULL, 
	base_quarter INTEGER NOT NULL, 
	floating_population BIGINT, 
	resident_population BIGINT, 
	working_population BIGINT, 
	consumption_index FLOAT, 
	avg_monthly_income BIGINT, 
	total_spending BIGINT, 
	avg_open_months FLOAT, 
	avg_closed_months FLOAT, 
	change_indicator VARCHAR(20), 
	change_indicator_name VARCHAR(30), 
	PRIMARY KEY (metric_id), 
	UNIQUE (area_id, base_quarter), 
	FOREIGN KEY(area_id) REFERENCES commercial_areas (area_id)
);

CREATE INDEX ix_area_metrics_area_id ON area_metrics (area_id);

CREATE TABLE data_ingestion_logs (
	log_id BIGSERIAL NOT NULL, 
	source_id BIGINT NOT NULL, 
	ingested_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	row_count INTEGER NOT NULL, 
	error_message TEXT, 
	max_quarter INTEGER, 
	PRIMARY KEY (log_id), 
	FOREIGN KEY(source_id) REFERENCES data_sources (source_id)
);

CREATE INDEX ix_data_ingestion_logs_source_id ON data_ingestion_logs (source_id);

CREATE TABLE industry_licenses (
	category_id BIGINT NOT NULL, 
	license_name VARCHAR(50) NOT NULL, 
	legal_basis VARCHAR(100), 
	PRIMARY KEY (category_id), 
	FOREIGN KEY(category_id) REFERENCES business_categories (category_id)
);

CREATE TABLE places (
	place_id BIGSERIAL NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	aliases VARCHAR(255) NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	latitude FLOAT NOT NULL, 
	longitude FLOAT NOT NULL, 
	area_id BIGINT, 
	PRIMARY KEY (place_id), 
	FOREIGN KEY(area_id) REFERENCES commercial_areas (area_id)
);

CREATE INDEX ix_places_name ON places (name);

CREATE TABLE rent_metrics (
	rent_id BIGSERIAL NOT NULL, 
	area_id BIGINT NOT NULL, 
	avg_monthly_rent BIGINT, 
	rent_per_square_meter INTEGER, 
	rent_per_3_3m2 INTEGER, 
	rent_level VARCHAR(30), 
	base_quarter INTEGER NOT NULL, 
	base_date DATE NOT NULL, 
	PRIMARY KEY (rent_id), 
	UNIQUE (area_id, base_quarter), 
	FOREIGN KEY(area_id) REFERENCES commercial_areas (area_id)
);

CREATE INDEX ix_rent_metrics_area_id ON rent_metrics (area_id);

CREATE TABLE sales_metrics (
	sales_id BIGSERIAL NOT NULL, 
	area_id BIGINT NOT NULL, 
	category_id BIGINT NOT NULL, 
	base_quarter INTEGER NOT NULL, 
	base_date DATE NOT NULL, 
	quarterly_sales BIGINT, 
	quarterly_tx_count BIGINT, 
	breakdown_json TEXT, 
	PRIMARY KEY (sales_id), 
	UNIQUE (area_id, category_id, base_quarter), 
	FOREIGN KEY(area_id) REFERENCES commercial_areas (area_id), 
	FOREIGN KEY(category_id) REFERENCES business_categories (category_id)
);

CREATE INDEX ix_sales_metrics_area_id ON sales_metrics (area_id);

CREATE INDEX ix_sales_metrics_category_id ON sales_metrics (category_id);

CREATE TABLE startup_closure_history (
	history_id BIGSERIAL NOT NULL, 
	area_id BIGINT NOT NULL, 
	category_id BIGINT NOT NULL, 
	startup_count INTEGER NOT NULL, 
	closure_count INTEGER NOT NULL, 
	closure_rate FLOAT, 
	survival_rate_3y FLOAT, 
	base_year INTEGER NOT NULL, 
	PRIMARY KEY (history_id), 
	UNIQUE (area_id, category_id, base_year), 
	FOREIGN KEY(area_id) REFERENCES commercial_areas (area_id), 
	FOREIGN KEY(category_id) REFERENCES business_categories (category_id)
);

CREATE INDEX ix_startup_closure_history_category_id ON startup_closure_history (category_id);

CREATE INDEX ix_startup_closure_history_area_id ON startup_closure_history (area_id);

CREATE TABLE store_statistics (
	store_stat_id BIGSERIAL NOT NULL, 
	area_id BIGINT NOT NULL, 
	category_id BIGINT NOT NULL, 
	base_quarter INTEGER NOT NULL, 
	base_date DATE NOT NULL, 
	store_count INTEGER NOT NULL, 
	total_store_count INTEGER NOT NULL, 
	franchise_count INTEGER NOT NULL, 
	opening_count INTEGER NOT NULL, 
	closure_count INTEGER NOT NULL, 
	PRIMARY KEY (store_stat_id), 
	UNIQUE (area_id, category_id, base_quarter), 
	FOREIGN KEY(area_id) REFERENCES commercial_areas (area_id), 
	FOREIGN KEY(category_id) REFERENCES business_categories (category_id)
);

CREATE INDEX ix_store_statistics_category_id ON store_statistics (category_id);

CREATE INDEX ix_store_statistics_area_id ON store_statistics (area_id);

CREATE TABLE break_even_analyses (
	break_even_id BIGSERIAL NOT NULL, 
	request_id BIGINT NOT NULL, 
	category_id BIGINT NOT NULL, 
	monthly_fixed_cost BIGINT NOT NULL, 
	variable_cost_rate FLOAT NOT NULL, 
	avg_transaction_amount BIGINT NOT NULL, 
	required_monthly_sales BIGINT NOT NULL, 
	required_daily_customers BIGINT NOT NULL, 
	other_fixed BIGINT NOT NULL, 
	depreciation BIGINT NOT NULL, 
	card_fee_rate FLOAT NOT NULL, 
	cogs_rate FLOAT NOT NULL, 
	operating_days INTEGER NOT NULL, 
	achievability_ratio FLOAT, 
	cost_pressure VARCHAR(10), 
	payback_months BIGINT, 
	input_json TEXT NOT NULL, 
	result_json TEXT NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (break_even_id), 
	FOREIGN KEY(request_id) REFERENCES analysis_requests (request_id) ON DELETE CASCADE, 
	FOREIGN KEY(category_id) REFERENCES business_categories (category_id)
);

CREATE INDEX ix_break_even_analyses_request_id ON break_even_analyses (request_id);

CREATE TABLE recommendation_results (
	recommendation_id BIGSERIAL NOT NULL, 
	request_id BIGINT NOT NULL, 
	model_type VARCHAR(50) NOT NULL, 
	model_version VARCHAR(30) NOT NULL, 
	weights_json TEXT NOT NULL, 
	f_applied BOOLEAN NOT NULL, 
	f_note TEXT, 
	n_candidates INTEGER NOT NULL, 
	n_low_score INTEGER DEFAULT '0' NOT NULL, 
	empty_reason TEXT, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (recommendation_id), 
	UNIQUE (request_id), 
	FOREIGN KEY(request_id) REFERENCES analysis_requests (request_id) ON DELETE CASCADE
);

CREATE TABLE request_areas (
	request_area_id BIGSERIAL NOT NULL, 
	request_id BIGINT NOT NULL, 
	area_id BIGINT NOT NULL, 
	is_primary BOOLEAN NOT NULL, 
	PRIMARY KEY (request_area_id), 
	FOREIGN KEY(request_id) REFERENCES analysis_requests (request_id) ON DELETE CASCADE, 
	FOREIGN KEY(area_id) REFERENCES commercial_areas (area_id)
);

CREATE INDEX ix_request_areas_request_id ON request_areas (request_id);

CREATE TABLE request_industries (
	request_industry_id BIGSERIAL NOT NULL, 
	request_id BIGINT NOT NULL, 
	category_id BIGINT NOT NULL, 
	preference_order INTEGER NOT NULL, 
	PRIMARY KEY (request_industry_id), 
	FOREIGN KEY(request_id) REFERENCES analysis_requests (request_id) ON DELETE CASCADE, 
	FOREIGN KEY(category_id) REFERENCES business_categories (category_id)
);

CREATE INDEX ix_request_industries_request_id ON request_industries (request_id);

CREATE TABLE risk_assessments (
	risk_id BIGSERIAL NOT NULL, 
	request_id BIGINT NOT NULL, 
	category_id BIGINT NOT NULL, 
	area_id BIGINT NOT NULL, 
	risk_score INTEGER NOT NULL, 
	risk_level VARCHAR(30) NOT NULL, 
	summary TEXT, 
	pred_annual_rate FLOAT NOT NULL, 
	location_risk_pct INTEGER, 
	location_risk_level VARCHAR(30), 
	confidence VARCHAR(10) NOT NULL, 
	model_version VARCHAR(30) NOT NULL, 
	reference_json TEXT, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (risk_id), 
	FOREIGN KEY(request_id) REFERENCES analysis_requests (request_id) ON DELETE CASCADE, 
	FOREIGN KEY(category_id) REFERENCES business_categories (category_id), 
	FOREIGN KEY(area_id) REFERENCES commercial_areas (area_id)
);

CREATE INDEX ix_risk_assessments_request_id ON risk_assessments (request_id);

CREATE TABLE action_reports (
	report_id BIGSERIAL NOT NULL, 
	public_id VARCHAR(36) NOT NULL, 
	request_id BIGINT NOT NULL, 
	recommendation_id BIGINT, 
	risk_id BIGINT, 
	break_even_id BIGINT, 
	category_id BIGINT NOT NULL, 
	one_line_summary TEXT NOT NULL, 
	policy_ctx_json TEXT, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (report_id), 
	FOREIGN KEY(request_id) REFERENCES analysis_requests (request_id) ON DELETE CASCADE, 
	FOREIGN KEY(recommendation_id) REFERENCES recommendation_results (recommendation_id), 
	FOREIGN KEY(risk_id) REFERENCES risk_assessments (risk_id), 
	FOREIGN KEY(break_even_id) REFERENCES break_even_analyses (break_even_id), 
	FOREIGN KEY(category_id) REFERENCES business_categories (category_id)
);

CREATE UNIQUE INDEX ix_action_reports_public_id ON action_reports (public_id);

CREATE INDEX ix_action_reports_request_id ON action_reports (request_id);

CREATE TABLE recommendation_items (
	item_id BIGSERIAL NOT NULL, 
	recommendation_id BIGINT NOT NULL, 
	category_id BIGINT NOT NULL, 
	item_type VARCHAR(10) NOT NULL, 
	rank_order INTEGER, 
	suitability_score FLOAT, 
	reason TEXT, 
	caution TEXT, 
	demand_score FLOAT, 
	stability_score FLOAT, 
	cost_score FLOAT, 
	achievability_ratio FLOAT, 
	eligible BOOLEAN NOT NULL, 
	ineligible_reason VARCHAR(100), 
	detail_json TEXT, 
	PRIMARY KEY (item_id), 
	FOREIGN KEY(recommendation_id) REFERENCES recommendation_results (recommendation_id) ON DELETE CASCADE, 
	FOREIGN KEY(category_id) REFERENCES business_categories (category_id)
);

CREATE INDEX ix_recommendation_items_recommendation_id ON recommendation_items (recommendation_id);

CREATE TABLE risk_factors (
	factor_id BIGSERIAL NOT NULL, 
	risk_id BIGINT NOT NULL, 
	factor_code VARCHAR(30) NOT NULL, 
	factor_name VARCHAR(100) NOT NULL, 
	label VARCHAR(100) NOT NULL, 
	effect_pct FLOAT NOT NULL, 
	x_value FLOAT, 
	explanation TEXT, 
	PRIMARY KEY (factor_id), 
	FOREIGN KEY(risk_id) REFERENCES risk_assessments (risk_id) ON DELETE CASCADE
);

CREATE INDEX ix_risk_factors_risk_id ON risk_factors (risk_id);

CREATE TABLE action_items (
	action_id BIGSERIAL NOT NULL, 
	report_id BIGINT NOT NULL, 
	policy_id BIGINT, 
	action_type VARCHAR(50) NOT NULL, 
	action_content TEXT NOT NULL, 
	priority INTEGER NOT NULL, 
	is_done BOOLEAN DEFAULT false NOT NULL, 
	PRIMARY KEY (action_id), 
	FOREIGN KEY(report_id) REFERENCES action_reports (report_id) ON DELETE CASCADE, 
	FOREIGN KEY(policy_id) REFERENCES policy_supports (policy_id)
);

CREATE INDEX ix_action_items_report_id ON action_items (report_id);

CREATE TABLE saved_reports (
	saved_report_id BIGSERIAL NOT NULL, 
	device_key_hash VARCHAR(64), 
	user_id BIGINT, 
	report_id BIGINT NOT NULL, 
	memo TEXT, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	PRIMARY KEY (saved_report_id), 
	CONSTRAINT uq_saved_reports_device_report UNIQUE (device_key_hash, report_id), 
	FOREIGN KEY(user_id) REFERENCES users (user_id) ON DELETE CASCADE, 
	FOREIGN KEY(report_id) REFERENCES action_reports (report_id) ON DELETE CASCADE
);

CREATE INDEX ix_saved_reports_user_id ON saved_reports (user_id);

CREATE INDEX ix_saved_reports_device_key_hash ON saved_reports (device_key_hash);
