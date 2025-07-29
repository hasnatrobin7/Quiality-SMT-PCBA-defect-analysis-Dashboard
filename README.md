# AOI Defect Dashboard

A comprehensive Streamlit-based dashboard for analyzing Automated Optical Inspection (AOI) defect data from PCB manufacturing lines. This tool processes raw AOI exports, classifies defects into meaningful categories, and provides interactive visualization and filtering capabilities.

## 🚀 Features

### Data Processing
- **Automated Classification**: Classifies defects into four categories:
  - **Real**: Confirmed defects requiring rework
  - **False**: Operator-cleared false positives  
  - **Suspect**: Pending operator review
  - **Fixed from previously caught**: Previously flagged defects no longer detected

- **Loop Consolidation**: Merges multiple inspection passes into single defect records
- **Database Storage**: SQLite database for fast querying and persistence
- **Batch Processing**: Handle multiple AOI export files simultaneously

### Interactive Dashboard
- **Real-time Filtering**: Filter by outcome, date/time ranges, part numbers, serial numbers, etc.
- **Customizable Layout**: Drag-and-drop interface with resizable sections
- **Multiple Visualizations**:
  - Summary metrics with live counts
  - Top 20 Ref ID distribution charts
  - Component PN analysis
  - Suspect queue for operator review
  - Pivot tables for cross-analysis

- **Export Capabilities**: Download filtered data and pivot tables as Excel files
- **Performance Optimized**: Cached operations for large datasets

## 📋 Requirements

- Python 3.8+
- Windows/Linux/macOS
- 4GB+ RAM recommended for large datasets

## 🛠️ Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/aoi-defect-dashboard.git
   cd aoi-defect-dashboard
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Optional: Install layout customization**
   ```bash
   pip install streamlit-sortables
   ```

## 🎯 Quick Start

### 1. Process AOI Data

Place your AOI export files (Excel format) in the project directory. Files should be named like `Defect RawData - YYYY-MM-DD.xlsx`.

**Option A: Process all files**
```bash
python Cogi-Defect/ingest_to_db.py
```

**Option B: Process specific file**
```bash
python Cogi-Defect/aoi_classify.py "Defect RawData - 2025-01-26.xlsx" output.xlsx
```

### 2. Launch Dashboard

```bash
streamlit run Cogi-Defect/app.py
```

Open your browser to `http://localhost:8501`

## 📊 Using the Dashboard

### Filters
The dashboard provides comprehensive filtering options:

- **Outcome**: Filter by defect classification (Real, False, Suspect, etc.)
- **Date/Time**: 
  - Preset ranges (Daily, Weekly, Monthly)
  - Custom date/time ranges
- **Manufacturing Data**:
  - Part Number
  - Component PN  
  - Serial Number
  - Ref ID
  - Machine Name
  - Operation Name
  - Line Name

### Layout Customization
Enable "Customize layout" in the sidebar to:
- Drag sections to reorder
- Adjust width (1-12 grid columns)
- Modify height for charts and tables
- Change chart colors
- Save layouts permanently

### Data Views

1. **Summary Counts**: Live metrics for each outcome category
2. **Ref ID Distribution**: Top 20 reference designators with most defects
3. **Component Analysis**: Defect distribution by component part number
4. **Suspect Queue**: Items awaiting operator review
5. **Data Table**: Full filterable dataset with export capability
6. **Pivot Analysis**: Cross-tabulation of defects by multiple dimensions

## 🔧 Configuration

### Data Structure Requirements

Your AOI export should contain these columns:
- `SerialNumber`: PCB serial number
- `Ref_Id`: Reference designator (e.g., C100, R205.1)
- `DefectCode`: Type of defect detected
- `ReworkStatus`: One of "Reworkable", "Overridden", "False call"
- Optional: `PartNumber`, `ComponentPN`, `MachineName`, etc.

### Layout Persistence

Dashboard layouts are automatically saved to `layout.json` in the project directory. This includes:
- Section order and positioning
- Width/height settings
- Chart colors and preferences

## 📁 Project Structure

```
aoi-defect-dashboard/
├── Cogi-Defect/
│   ├── app.py                    # Main Streamlit dashboard
│   ├── aoi_classify.py           # Single-file classification script
│   ├── ingest_to_db.py           # Batch processing to database
│   └── requirements.txt          # Python dependencies
├── aoi_defects.db               # SQLite database (auto-generated)
├── layout.json                  # UI layout settings (auto-generated)
├── Defect RawData - *.xlsx      # AOI export files
└── README.md                    # This file
```

## 🔄 Workflow

1. **Export Data**: Export defect data from your AOI system
2. **Process**: Run `ingest_to_db.py` to classify and store data
3. **Analyze**: Use the dashboard to filter, visualize, and export insights
4. **Review**: Operators can identify suspects requiring attention
5. **Repeat**: Add new exports and refresh data as needed

## ⚡ Performance Tips

- **Large Datasets**: The dashboard automatically limits display rows for performance
- **Caching**: Database queries and computations are cached for speed
- **Filtering**: Use specific filters to reduce data volume
- **Exports**: Full datasets can be downloaded regardless of display limits

## 🛠️ Troubleshooting

### Common Issues

**Database not found**
- Ensure you've run `ingest_to_db.py` first
- Check that `aoi_defects.db` exists in the project directory

**Missing columns**
- Verify your AOI export contains required columns
- Check column names match expected format

**Performance issues**
- Reduce filter scope for large datasets
- Use specific date ranges rather than "all time"
- Consider processing data in smaller batches

**Layout not saving**
- Ensure write permissions in project directory
- Check that `layout.json` is being created

## 🔧 Advanced Usage

### Custom Processing

Modify `aoi_classify.py` to adjust classification logic:

```python
def classify(row):
    """Customize defect classification rules here"""
    if row["False call"] > 0:
        return "False"
    # Add your custom logic...
```

### Database Queries

Access the database directly for custom analysis:

```python
import sqlite3
import pandas as pd

conn = sqlite3.connect('aoi_defects.db')
df = pd.read_sql("SELECT * FROM defects WHERE Outcome = 'Real'", conn)
conn.close()
```

## 📈 Metrics and KPIs

The dashboard enables tracking of key manufacturing metrics:

- **Escape Rate**: Real defects not caught initially
- **False Call Rate**: Nuisance alarms requiring operator time
- **Review Efficiency**: Suspect queue backlog
- **Component Reliability**: Defect patterns by part number
- **Line Performance**: Defect rates by production line

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🆘 Support

For questions or issues:
1. Check the troubleshooting section above
2. Search existing GitHub issues
3. Create a new issue with detailed description and sample data

## 🔄 Version History

- **v1.0**: Initial release with basic classification and dashboard
- **v1.1**: Added customizable layouts and performance optimizations
- **v1.2**: Enhanced filtering and pivot table functionality
- **v1.3**: Database persistence and batch processing

---

**Made for manufacturing excellence** 🏭✨