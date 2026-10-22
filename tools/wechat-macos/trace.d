#pragma D option quiet

pid$target::CC_MD5:entry
/arg1 == 24/
{
    this->p = (unsigned char *)copyin(arg0, 16);
    printf("MD5KEY %02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x\n",
        this->p[0], this->p[1], this->p[2], this->p[3],
        this->p[4], this->p[5], this->p[6], this->p[7],
        this->p[8], this->p[9], this->p[10], this->p[11],
        this->p[12], this->p[13], this->p[14], this->p[15]);
}

pid$target::CCCrypt:entry
/arg4 == 16/
{
    this->k = (unsigned char *)copyin(arg3, 16);
    printf("CCCKEY %02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x\n",
        this->k[0], this->k[1], this->k[2], this->k[3],
        this->k[4], this->k[5], this->k[6], this->k[7],
        this->k[8], this->k[9], this->k[10], this->k[11],
        this->k[12], this->k[13], this->k[14], this->k[15]);
}

pid$target::CCCryptorCreate:entry
/arg4 == 16/
{
    this->k = (unsigned char *)copyin(arg3, 16);
    printf("CRTKEY %02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x\n",
        this->k[0], this->k[1], this->k[2], this->k[3],
        this->k[4], this->k[5], this->k[6], this->k[7],
        this->k[8], this->k[9], this->k[10], this->k[11],
        this->k[12], this->k[13], this->k[14], this->k[15]);
}

pid$target::CCCryptorCreateWithMode:entry
/arg6 == 16/
{
    this->k = (unsigned char *)copyin(arg5, 16);
    printf("MODKEY %02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x\n",
        this->k[0], this->k[1], this->k[2], this->k[3],
        this->k[4], this->k[5], this->k[6], this->k[7],
        this->k[8], this->k[9], this->k[10], this->k[11],
        this->k[12], this->k[13], this->k[14], this->k[15]);
}

profile-1s
/++this->n >= 15/
{
    exit(0);
}
