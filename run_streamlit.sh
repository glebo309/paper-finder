#!/bin/bash
# Quick launcher for Paper Finder Streamlit app

echo "================================================"
echo "  Paper Finder - Streamlit Web Interface"
echo "================================================"
echo ""

# Get local IP
LOCAL_IP=$(ifconfig | grep "inet " | grep -v 127.0.0.1 | awk '{print $2}' | head -n 1)

echo "Starting server..."
echo ""
echo "Access URLs:"
echo "  Local:   http://localhost:8501"
echo "  Network: http://$LOCAL_IP:8501"
echo ""
echo "Share the network URL with your lab colleagues!"
echo ""
echo "Press Ctrl+C to stop"
echo "================================================"
echo ""

# Run Streamlit
streamlit run streamlit_app.py --server.address 0.0.0.0 --server.port 8501
