docker run -d -it --network host ^
    -v %cd%/data:/app/data ^
    --name to_chat --restart always to_chat