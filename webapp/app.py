import os
import broadlink
import base64
from flask import Flask, render_template, request, send_file, Response, jsonify
from lacrosse_gen import create_sub_file, generate_broadlink_payload

app = Flask(__name__)

TEMPLATE_PATH = 'LaCrosse-TX141TH-BV2-raw.sub'

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/discover_mac', methods=['POST'])
def discover_mac():
    try:
        data = request.json
        ip = data.get('ip')
        if not ip:
            return jsonify({"error": "IP is required"}), 400
        
        device = broadlink.hello(ip)
        if not device:
            return jsonify({"error": f"Could not find device at {ip}"}), 404
            
        mac_addr = ':'.join(format(x, '02x') for x in device.mac).upper()
        return jsonify({"mac": mac_addr})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/generate', methods=['POST'])
def generate():
    try:
        temp_f = float(request.form.get('temperature'))
        humidity = float(request.form.get('humidity'))
        
        # Ensure template exists in current dir
        if not os.path.exists(TEMPLATE_PATH):
            return "Template file not found", 404
            
        new_sub_content = create_sub_file(TEMPLATE_PATH, temp_f, humidity)
        
        filename = f"LaCrosse_{temp_f}F_{humidity}H.sub"
        
        return Response(
            new_sub_content,
            mimetype="text/plain",
            headers={"Content-disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        return f"Error: {str(e)}", 400

@app.route('/send_broadlink', methods=['POST'])
def send_broadlink():
    try:
        data = request.json
        temp_f = float(data.get('temperature'))
        humidity = float(data.get('humidity'))
        ip = data.get('broadlink_ip')
        mac = data.get('broadlink_mac')
        repeats = int(data.get('broadlink_repeats', 6))
        
        if not ip or not mac:
            return jsonify({"error": "Broadlink IP and MAC are required"}), 400
            
        # Parse MAC (expecting format like AA:BB:CC:DD:EE:FF or AABBCCDDEEFF)
        mac_clean = mac.replace(':', '').replace('-', '')
        mac_bytes = bytes.fromhex(mac_clean)
        
        payload = generate_broadlink_payload(temp_f, humidity, repeats=repeats)
        
        # Connect to device
        try:
            device = broadlink.hello(ip)
        except Exception:
            # Fallback: Manually construct device if hello() fails
            # 0x6026 is the most common RM4 Pro type
            device = broadlink.gendevice(0x6026, (ip, 80), mac_bytes)
            
        if not device:
            return jsonify({"error": f"Could not find Broadlink device at {ip}"}), 404
            
        device.auth()
        device.send_data(payload)
        
        b64_payload = base64.b64encode(payload).decode('utf-8')
        
        return jsonify({
            "status": "success",
            "ip": ip,
            "b64": b64_payload,
            "message": f"Sent to RM4 Pro at {ip}"
        })
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5005)
