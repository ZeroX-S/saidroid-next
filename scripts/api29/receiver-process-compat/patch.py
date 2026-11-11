import re


WORKER_SIGNATURE = '.method public blacklist run()V'
ENDPOINT_SIGNATURE = '.method protected blacklist onTransact(ILandroid/os/Parcel;Landroid/os/Parcel;I)Z'
STARTUP = '''    invoke-static {v1, v2, v3}, LSdReceiverProcess;->start(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)V

    const-string v1, "Receiver process startup deadline"

    invoke-static {v0, v1}, LSdProcessStartup;->awaitEndpoint(Ljava/lang/String;Ljava/lang/String;)Landroid/os/IBinder;

    move-result-object v1
'''
INTERRUPT = '''    instance-of v1, v0, Ljava/lang/InterruptedException;

    if-eqz v1, :receiver_dispatch_failure

    invoke-static {}, Ljava/lang/Thread;->currentThread()Ljava/lang/Thread;

    move-result-object v1

    invoke-virtual {v1}, Ljava/lang/Thread;->interrupt()V

    :receiver_dispatch_failure
'''
DISPATCH = '''    const/16 v6, 0x9

    if-ne v0, v6, :existing_service_transaction

    invoke-static {v1, v2}, LSdReceiverProcess;->dispatch(Landroid/os/Parcel;Landroid/os/Parcel;)Z

    move-result v0

    return v0

    :existing_service_transaction
'''


def method_span(text, signature):
    matches = list(re.finditer(re.escape(signature) + r'\n.*?^\.end method$', text,
                              re.MULTILINE | re.DOTALL))
    if len(matches) != 1:
        raise ValueError('Exactly one method is required: ' + signature)
    return matches[0]


def patch_worker(text):
    selected = method_span(text, WORKER_SIGNATURE)
    method = selected.group()
    if STARTUP in method and INTERRUPT in method:
        return text
    anchor = '    invoke-static {v1, v2, v3}, Lorg/saildroid/host/HostApi;->startReceiverProcess(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)V\n'
    ending = '    .line 64\n    :cond_52\n'
    if method.count(anchor) != 1 or method.count(ending) != 1 or '.registers 6' not in method:
        raise ValueError('Unsupported receiver worker layout')
    start = method.index(anchor)
    end = method.index(ending, start)
    method = method[:start] + STARTUP + '\n' + method[end:]
    caught = '    :catch_a5\n    move-exception v0\n'
    if method.count(caught) != 1:
        raise ValueError('Unsupported receiver exception handler')
    method = method.replace(caught, caught + '\n' + INTERRUPT)
    return text[:selected.start()] + method + text[selected.end():]


def patch_endpoint(text):
    selected = method_span(text, ENDPOINT_SIGNATURE)
    method = selected.group()
    if DISPATCH in method:
        return text
    upper_bound = '    const/16 v3, 0x8\n\n    if-le v0, v3, :cond_1a'
    identity_check = '    :cond_1a\n    invoke-static {}, Landroid/os/Binder;->getCallingUid()I'
    dispatch_anchor = '    const/4 v4, 0x0\n\n    if-ne v0, v3, :cond_7d'
    required = ['.registers 20', '    if-ne v6, v7, :cond_16f',
                '    invoke-virtual {v1, v4}, Landroid/os/Parcel;->enforceInterface(Ljava/lang/String;)V']
    if any(value not in method for value in required) or any(
            method.count(value) != 1 for value in [upper_bound, identity_check, dispatch_anchor]):
        raise ValueError('Unsupported service endpoint layout')
    method = method.replace(upper_bound, upper_bound.replace('0x8', '0x9'))
    method = method.replace(identity_check, identity_check.replace('    invoke-static',
                            '    const/16 v3, 0x8\n\n    invoke-static', 1))
    method = method.replace(dispatch_anchor, dispatch_anchor.replace('    if-ne', DISPATCH + '\n    if-ne', 1))
    return text[:selected.start()] + method + text[selected.end():]
