for camera in 'camera1' 'camera2' 'camera3'; do
  echo updating $camera
  ./update_reolink.py --base_url https://$camera.example.com
done
