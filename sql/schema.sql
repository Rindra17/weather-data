CREATE TABLE dim_time (
    time_id SERIAL PRIMARY KEY,
    reading_at TIMESTAMPTZ NOT NULL UNIQUE,
    date DATE,
    hour INTEGER,
    day_of_week VARCHAR(10),
    is_weekend BOOLEAN,
    month INTEGER,
    year INTEGER,
    quarter INTEGER
);

CREATE TABLE dim_city (
    city_id SERIAL PRIMARY KEY,
    city_name VARCHAR(100) NOT NULL UNIQUE,
    country VARCHAR(100),
    latitude DECIMAL(10,6),
    longitude DECIMAL(10, 6)
);

CREATE TABLE fact_air_quality (
    fact_id SERIAL PRIMARY KEY,
    time_id INTEGER REFERENCES dim_time(time_id),
    city_id INTEGER REFERENCES dim_city(city_id),
    aqi INTEGER,
    aqi_label VARCHAR(20),
    co DECIMAL(10,3),
    no DECIMAL(10,3),
    no2 DECIMAL(10,3),
    o3 DECIMAL(10,3),
    so2 DECIMAL(10,3),
    pm2_5 DECIMAL(10,3),
    pm10 DECIMAL(10,3),
    nh3 DECIMAL(10,3),
    dominant_pollutant VARCHAR(20),
    UNIQUE (time_id, city_id)
);
