from setuptools import setup, find_packages

setup(
    name="photo-organizer",
    version="0.1.0",
    description="EXIF-aware photo organiser CLI — core engine for macOS SwiftUI app",
    python_requires=">=3.10",
    packages=find_packages(exclude=["tests*"]),
    install_requires=["Pillow>=10.0.0", "omegaconf>=2.3.0", "rich>=13.7.0"],
    extras_require={
        "dev": ["pytest>=8.0.0", "pytest-cov>=5.0.0"],
        "progress": ["rich>=13.7.0"],
        "api": ["fastapi>=0.111.0", "uvicorn>=0.29.0"],
    },
    entry_points={
        "console_scripts": [
            "photo-organizer=photo_organizer.main:main",
            "photo-organizer-network-backup=photo_organizer.network_backup:main",
            "photo-organizer-cloud-copy=photo_organizer.cloud_copy:main",
            "photo-organizer-ftp-upload=photo_organizer.ftp_upload:main",
            "photo-organizer-workflow=photo_organizer.workflow:main",
            "photo-organizer-run-all=photo_organizer.workflow:main",
        ]
    },
)
