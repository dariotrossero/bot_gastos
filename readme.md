copy service file to etc/systemd/system/
cp bot-gastos.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now bot-gastos
systemctl status bot-gastos