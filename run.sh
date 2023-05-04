# Run as daemon
docker run -d -it --network host \
    -v ./data:/app/data \
    --name to_chat --restart always to_chat
