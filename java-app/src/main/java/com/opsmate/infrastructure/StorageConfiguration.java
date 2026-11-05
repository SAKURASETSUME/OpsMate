package com.opsmate.infrastructure;

import javax.sql.DataSource;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.core.JdbcTemplate;

@Configuration
public class StorageConfiguration {
    @Bean
    DataSource sqlite(RuntimePaths paths) {
        DriverManagerDataSource source = new DriverManagerDataSource();
        source.setDriverClassName("org.sqlite.JDBC");
        source.setUrl("jdbc:sqlite:" + paths.data().resolve("opsmate.db")
            + "?busy_timeout=15000");
        new JdbcTemplate(source).execute("PRAGMA journal_mode=WAL");
        return source;
    }
}
