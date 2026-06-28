{
  "app": {
    "name": "SysAdmin Toolkit",
    "version": "1.0.0",
    "theme": "dark",
    "language": "de"
  },
  "paths": {
    "backup_dir": "data/backups",
    "log_dir": "data/logs",
    "report_dir": "data/reports",
    "script_dir": "data/scripts"
  },
  "network": {
    "default_ping_count": 4,
    "default_ping_timeout_ms": 1000,
    "port_scan_timeout_s": 0.5,
    "common_ports": [21, 22, 23, 25, 53, 80, 110, 143, 443, 445, 3306, 3389, 5432, 8080]
  },
  "backup": {
    "compression": "zip",
    "keep_versions": 5
  },
  "monitoring": {
    "refresh_interval_ms": 2000,
    "cpu_warning_percent": 80,
    "ram_warning_percent": 85,
    "disk_warning_percent": 90
  },
  "logging": {
    "level": "INFO"
  }
}