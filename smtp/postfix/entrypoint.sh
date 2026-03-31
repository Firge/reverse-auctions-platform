#!/bin/sh
set -eu

: "${RELAY_HOST:=smtp.yandex.ru}"
: "${RELAY_PORT:=587}"
: "${RELAY_TLS:=yes}"
: "${RELAY_INET_PROTOCOLS:=all}"
: "${MYHOSTNAME:=mail.local}"
: "${MYNETWORKS:=127.0.0.0/8,172.16.0.0/12}"
: "${RELAY_USERNAME:=}"
: "${RELAY_PASSWORD:=}"

postconf -e "myhostname = ${MYHOSTNAME}"
postconf -e "mydestination ="
postconf -e "relayhost = [${RELAY_HOST}]:${RELAY_PORT}"
postconf -e "inet_interfaces = all"
postconf -e "inet_protocols = ${RELAY_INET_PROTOCOLS}"
postconf -e "mynetworks = ${MYNETWORKS}"
postconf -e "smtpd_relay_restrictions = permit_mynetworks,reject_unauth_destination"
postconf -e "smtpd_recipient_restrictions = permit_mynetworks,reject_unauth_destination"
postconf -F smtp/unix/chroot=n
postconf -F relay/unix/chroot=n
postconf -e "smtp_tls_security_level = ${RELAY_TLS}"
postconf -e "smtp_tls_CAfile = /etc/ssl/certs/ca-certificates.crt"
postconf -e "smtp_tls_loglevel = 1"
postconf -e "smtp_sasl_auth_enable = yes"
postconf -e "smtp_sasl_security_options = noanonymous"
postconf -e "smtp_sasl_tls_security_options = noanonymous"
postconf -e "smtp_sasl_password_maps = hash:/etc/postfix/sasl_passwd"

if [ -n "${RELAY_USERNAME}" ] && [ -n "${RELAY_PASSWORD}" ]; then
  echo "[${RELAY_HOST}]:${RELAY_PORT} ${RELAY_USERNAME}:${RELAY_PASSWORD}" > /etc/postfix/sasl_passwd
  postmap /etc/postfix/sasl_passwd
  chmod 0600 /etc/postfix/sasl_passwd /etc/postfix/sasl_passwd.db
else
  : > /etc/postfix/sasl_passwd
  postmap /etc/postfix/sasl_passwd
  chmod 0600 /etc/postfix/sasl_passwd /etc/postfix/sasl_passwd.db
fi

exec postfix start-fg
