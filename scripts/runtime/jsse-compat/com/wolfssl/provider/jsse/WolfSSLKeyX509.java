/* WolfSSLKeyX509.java
 *
 * Copyright (C) 2006-2022 wolfSSL Inc.
 *
 * This file is part of wolfSSL.
 *
 * wolfSSL is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 2 of the License, or
 * (at your option) any later version.
 *
 * wolfSSL is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA
 */

package com.wolfssl.provider.jsse;

import java.net.Socket;
import java.security.KeyStore;
import java.security.KeyStoreException;
import java.security.Principal;
import java.security.PrivateKey;
import java.security.cert.Certificate;
import java.security.cert.CertificateEncodingException;
import java.security.cert.X509Certificate;
import java.util.ArrayList;
import java.util.Enumeration;

import javax.net.ssl.X509KeyManager;

import com.wolfssl.WolfSSLException;

/**
 * wolfSSL implementation of X509KeyManager
 *
 * @author wolfSSL
 */
public class WolfSSLKeyX509 implements X509KeyManager{
    private KeyStore store;
    private char[] password;

    /**
     * Create new WolfSSLKeyX509 object
     *
     * @param in input KeyStore to use with this object
     * @param password input KeyStore password
     */
    public WolfSSLKeyX509(KeyStore in, char[] password) {
        this.store = in;
        this.password = password;

        WolfSSLDebug.log(getClass(), WolfSSLDebug.INFO,
            "creating new WolfSSLKeyX509 object");
    }

    /**
     * Return array of aliases from current KeyStore that matches provided
     * type and issuers array.
     *
     * Returns:
     * null - if current KeyStore is null, error getting aliases from store,
     *        or no alias mathes found in current KeyStore.
     * String[] - aliases, if found that match type and/or issuers
     */
    private String[] getAliases(String type, Principal[] issuers) {
        if (store == null || type == null) return null;
        // Android10 KeyManagerImpl splits names such as EC_EC and EC_RSA.
        int split = type.indexOf('_');
        String keyAlgorithm = split < 0 ? type : type.substring(0, split);
        String signatureAlgorithm = split < 0 ? null : type.substring(split + 1);
        ArrayList<String> matches = new ArrayList<String>();
        try {
            Enumeration<String> aliases = store.aliases();
            while (aliases.hasMoreElements()) {
                String alias = aliases.nextElement();
                if (!store.isKeyEntry(alias) || getPrivateKey(alias) == null) continue;
                X509Certificate[] chain = getCertificateChain(alias);
                if (chain == null || chain.length == 0 || chain[0] == null) continue;
                if (!chain[0].getPublicKey().getAlgorithm().equals(keyAlgorithm)) continue;
                if (signatureAlgorithm != null && !chain[0].getSigAlgName()
                        .toUpperCase(java.util.Locale.US).contains(signatureAlgorithm)) continue;
                if (issuers == null || issuers.length == 0) {
                    matches.add(alias);
                    continue;
                }
                boolean accepted = false;
                for (X509Certificate cert : chain) {
                    if (cert == null) continue;
                    for (Principal issuer : issuers) {
                        if (cert.getIssuerX500Principal().equals(issuer)) {
                            accepted = true;
                            break;
                        }
                    }
                    if (accepted) break;
                }
                if (accepted) matches.add(alias);
            }
        } catch (KeyStoreException failure) {
            WolfSSLDebug.log(getClass(), WolfSSLDebug.ERROR,
                    "Error enumerating actual private key entries");
            return null;
        }
        return matches.isEmpty() ? null : matches.toArray(new String[0]);
    }

    public String[] getClientAliases(String type, Principal[] issuers) {

        WolfSSLDebug.log(getClass(), WolfSSLDebug.INFO,
            "entered getClientAliases()");

        return getAliases(type, issuers);
    }

    /* Note: Socket argument not used by wolfJSSE to choose aliases */
    public String chooseClientAlias(String[] type, Principal[] issuers,
                                    Socket sock) {
        int i;

        WolfSSLDebug.log(getClass(), WolfSSLDebug.INFO,
            "entered chooseClientAlias()");

        if (type == null) {
            return null;
        }

        for (i = 0; i < type.length; i++) {
            String[] all = getAliases(type[i], issuers);
            if (all != null) {
                return all[0];
            }
        }
        return null;
    }

    public String[] getServerAliases(String type, Principal[] issuers) {

        WolfSSLDebug.log(getClass(), WolfSSLDebug.INFO,
            "entered getServerAliases(), type: " + type);

        return getAliases(type, issuers);
    }

    public String chooseServerAlias(String type, Principal[] issuers,
                                    Socket sock) {

        WolfSSLDebug.log(getClass(), WolfSSLDebug.INFO,
            "entered chooseServerAlias(), type: " + type);

        /* for now using same behavior ad choose client alias */
        return chooseClientAlias(new String[]{ type }, issuers, sock);
    }

    @Override
    public X509Certificate[] getCertificateChain(String alias) {
        if (alias == null) return null;

        X509Certificate[] ret = null;

        WolfSSLDebug.log(getClass(), WolfSSLDebug.INFO,
            "entered getCertificateChain(), alias: " + alias);

        if (store == null) {
            return null;
        }

        try {
            Certificate[] certs = this.store.getCertificateChain(alias);
            if (certs != null) {
                int x509Cnt = 0;

                /* count up X509Certificate type in certs[] */
                for (int i = 0; i < certs.length; i++) {
                    if (certs[i] instanceof X509Certificate) {
                        x509Cnt++;
                    }
                }

                /* store into X509Certificate array */
                ret = new X509Certificate[x509Cnt];
                for (int i = 0; i < certs.length; i++) {
                    if (certs[i] instanceof X509Certificate) {
                        ret[i] = (X509Certificate)certs[i];
                    }
                }
            }

        } catch (KeyStoreException ex) {
            return null;
        }

        return ret;
    }

    @Override
    public PrivateKey getPrivateKey(String alias) {
        if (alias == null) return null;

        PrivateKey key = null;

        WolfSSLDebug.log(getClass(), WolfSSLDebug.INFO,
            "entered getPrivateKey(), alias: " + alias);

        try {
            key = (PrivateKey)store.getKey(alias, password);
        } catch (Exception e) {
           /* @TODO unable to get key */
        }
        return key;
    }
}

