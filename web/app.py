from flask import Flask, render_template, jsonify, request
import duckdb
import os

app = Flask(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data.duckdb')


def get_connection():
    return duckdb.connect(DB_PATH, read_only=True)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/tables')
def get_tables():
    """Get list of all tables in the database"""
    con = get_connection()
    tables = con.execute("SHOW TABLES").fetchall()
    con.close()
    return jsonify([t[0] for t in tables])


@app.route('/api/table/<table_name>/schema')
def get_table_schema(table_name):
    """Get schema for a specific table"""
    con = get_connection()
    try:
        # Validate table name exists
        tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
        if table_name not in tables:
            return jsonify({'error': 'Table not found'}), 404
        
        schema = con.execute(f"DESCRIBE {table_name}").fetchall()
        con.close()
        return jsonify([{'column': row[0], 'type': row[1]} for row in schema])
    except Exception as e:
        con.close()
        return jsonify({'error': str(e)}), 500


@app.route('/api/table/<table_name>/data')
def get_table_data(table_name):
    """Get data from a specific table with pagination"""
    con = get_connection()
    try:
        # Validate table name exists
        tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
        if table_name not in tables:
            return jsonify({'error': 'Table not found'}), 404
        
        # Pagination
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 100, type=int)
        per_page = min(per_page, 1000)  # Max 1000 rows per request
        offset = (page - 1) * per_page
        
        # Get total count
        total = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        
        # Get column names
        columns = [row[0] for row in con.execute(f"DESCRIBE {table_name}").fetchall()]
        
        # Get data
        rows = con.execute(f"SELECT * FROM {table_name} LIMIT {per_page} OFFSET {offset}").fetchall()
        con.close()
        
        return jsonify({
            'columns': columns,
            'rows': [list(row) for row in rows],
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': (total + per_page - 1) // per_page
        })
    except Exception as e:
        con.close()
        return jsonify({'error': str(e)}), 500


@app.route('/api/query', methods=['POST'])
def run_query():
    """Run a custom SQL query (read-only)"""
    data = request.get_json()
    query = data.get('query', '').strip()
    
    if not query:
        return jsonify({'error': 'No query provided'}), 400
    
    # Basic safety check - only allow SELECT queries
    if not query.upper().startswith('SELECT'):
        return jsonify({'error': 'Only SELECT queries are allowed'}), 400
    
    con = get_connection()
    try:
        result = con.execute(query).fetchall()
        columns = [desc[0] for desc in con.description]
        con.close()
        
        # Limit results to 1000 rows
        return jsonify({
            'columns': columns,
            'rows': [list(row) for row in result[:1000]],
            'truncated': len(result) > 1000
        })
    except Exception as e:
        con.close()
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
